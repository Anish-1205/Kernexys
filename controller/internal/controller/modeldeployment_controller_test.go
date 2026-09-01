// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

package controller

import (
	"context"
	"errors"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	platformv1alpha1 "github.com/kernexys/kernexys/controller/api/v1alpha1"
)

func TestFirstReconciliationCreatesOwnedResourcesAndStatus(t *testing.T) {
	modelDeployment := validModelDeployment()
	reconciler, counted := newTestReconciler(t, modelDeployment)

	reconcileSuccessfully(t, reconciler, modelDeployment)

	deployment := getDeployment(t, counted, modelDeployment)
	service := getService(t, counted, modelDeployment)
	if !metav1.IsControlledBy(deployment, modelDeployment) {
		t.Fatal("Deployment is not controlled by ModelDeployment")
	}
	if !metav1.IsControlledBy(service, modelDeployment) {
		t.Fatal("Service is not controlled by ModelDeployment")
	}
	if got := deployment.Spec.Template.Spec.Containers[0].Image; got != "kernexys/model-runtime:v1" {
		t.Fatalf("runtime image = %q, want kernexys/model-runtime:v1", got)
	}
	runtimeEnvironment := map[string]string{}
	for _, variable := range deployment.Spec.Template.Spec.Containers[0].Env {
		runtimeEnvironment[variable.Name] = variable.Value
	}
	if got := runtimeEnvironment["KERNEXYS_MODEL_NAME"]; got != "sentiment" {
		t.Fatalf("runtime model name = %q, want sentiment", got)
	}
	if got := runtimeEnvironment["KERNEXYS_MODEL_VERSION"]; got != "v1" {
		t.Fatalf("runtime model version = %q, want v1", got)
	}
	if got := runtimeEnvironment["KERNEXYS_RUNTIME_PORT"]; got != "8080" {
		t.Fatalf("runtime port = %q, want 8080", got)
	}
	if got := *deployment.Spec.Replicas; got != 1 {
		t.Fatalf("replicas = %d, want 1", got)
	}
	resources := deployment.Spec.Template.Spec.Containers[0].Resources
	if got := resources.Requests.Cpu().String(); got != "100m" {
		t.Fatalf("default CPU request = %q, want 100m", got)
	}
	if got := resources.Requests.Memory().String(); got != "128Mi" {
		t.Fatalf("default memory request = %q, want 128Mi", got)
	}
	if got := resources.Limits.Cpu().String(); got != "1" {
		t.Fatalf("default CPU limit = %q, want 1", got)
	}
	if got := resources.Limits.Memory().String(); got != "512Mi" {
		t.Fatalf("default memory limit = %q, want 512Mi", got)
	}
	if got := service.Spec.Ports[0].TargetPort.String(); got != "http" {
		t.Fatalf("service target port = %q, want http", got)
	}

	observed := getModelDeployment(t, counted, modelDeployment)
	if observed.Status.ObservedGeneration != modelDeployment.Generation {
		t.Fatalf("observed generation = %d, want %d", observed.Status.ObservedGeneration, modelDeployment.Generation)
	}
	if observed.Status.DesiredReplicas != 1 || observed.Status.ReadyReplicas != 0 {
		t.Fatalf("replica status = %d/%d, want 0/1", observed.Status.ReadyReplicas, observed.Status.DesiredReplicas)
	}
	if observed.Status.ActiveVersion != "" {
		t.Fatalf("active version = %q before readiness, want empty", observed.Status.ActiveVersion)
	}
	assertCondition(t, observed, platformv1alpha1.ConditionProgressing, metav1.ConditionTrue, "Reconciling")
	assertCondition(t, observed, platformv1alpha1.ConditionDegraded, metav1.ConditionFalse, "ReconcileSucceeded")
	if counted.creates != 2 || counted.statusUpdates != 1 {
		t.Fatalf("writes = creates:%d status:%d, want 2 and 1", counted.creates, counted.statusUpdates)
	}
}

func TestRepeatedReconciliationAndControllerRestartDoNotWrite(t *testing.T) {
	modelDeployment := validModelDeployment()
	reconciler, counted := newTestReconciler(t, modelDeployment)
	reconcileSuccessfully(t, reconciler, modelDeployment)
	counted.resetCounts()

	restarted := &ModelDeploymentReconciler{Client: counted, Scheme: reconciler.Scheme}
	reconcileSuccessfully(t, restarted, modelDeployment)

	if counted.creates != 0 || counted.updates != 0 || counted.statusUpdates != 0 {
		t.Fatalf(
			"repeated reconciliation wrote state: creates=%d updates=%d status=%d",
			counted.creates,
			counted.updates,
			counted.statusUpdates,
		)
	}
}

func TestReconciliationRepairsDeploymentDrift(t *testing.T) {
	modelDeployment := validModelDeployment()
	reconciler, counted := newTestReconciler(t, modelDeployment)
	reconcileSuccessfully(t, reconciler, modelDeployment)

	drifted := getDeployment(t, counted, modelDeployment)
	replicas := int32(9)
	drifted.Spec.Replicas = &replicas
	drifted.Spec.Template.Spec.Containers[0].Image = "tampered/image:latest"
	drifted.Labels["manual-drift"] = "true"
	if err := counted.Client.Update(context.Background(), drifted); err != nil {
		t.Fatalf("introduce Deployment drift: %v", err)
	}
	counted.resetCounts()

	reconcileSuccessfully(t, reconciler, modelDeployment)
	repaired := getDeployment(t, counted, modelDeployment)
	if *repaired.Spec.Replicas != 1 {
		t.Fatalf("repaired replicas = %d, want 1", *repaired.Spec.Replicas)
	}
	if repaired.Spec.Template.Spec.Containers[0].Image != "kernexys/model-runtime:v1" {
		t.Fatalf("runtime image was not repaired: %q", repaired.Spec.Template.Spec.Containers[0].Image)
	}
	if _, found := repaired.Labels["manual-drift"]; found {
		t.Fatal("manually added Deployment label was not removed")
	}
	if counted.updates != 1 {
		t.Fatalf("child updates = %d, want exactly 1", counted.updates)
	}
}

func TestReconciliationRecreatesMissingService(t *testing.T) {
	modelDeployment := validModelDeployment()
	reconciler, counted := newTestReconciler(t, modelDeployment)
	reconcileSuccessfully(t, reconciler, modelDeployment)

	service := getService(t, counted, modelDeployment)
	if err := counted.Client.Delete(context.Background(), service); err != nil {
		t.Fatalf("delete Service: %v", err)
	}
	counted.resetCounts()

	reconcileSuccessfully(t, reconciler, modelDeployment)
	_ = getService(t, counted, modelDeployment)
	if counted.creates != 1 {
		t.Fatalf("child creates = %d, want exactly 1", counted.creates)
	}
}

func TestInvalidDesiredStateIsDegradedWithoutRetry(t *testing.T) {
	modelDeployment := validModelDeployment()
	modelDeployment.Spec.Runtime.Image = ""
	reconciler, counted := newTestReconciler(t, modelDeployment)

	result, err := reconciler.Reconcile(context.Background(), requestFor(modelDeployment))
	if err != nil {
		t.Fatalf("invalid desired state returned retryable error: %v", err)
	}
	if result != (ctrl.Result{}) {
		t.Fatalf("result = %#v, want empty result", result)
	}
	observed := getModelDeployment(t, counted, modelDeployment)
	assertCondition(t, observed, platformv1alpha1.ConditionDegraded, metav1.ConditionTrue, "InvalidSpec")
	if counted.creates != 0 {
		t.Fatalf("invalid desired state created %d children", counted.creates)
	}
}

func TestWorkloadReadinessUpdatesActiveVersionAndConditions(t *testing.T) {
	modelDeployment := validModelDeployment()
	reconciler, counted := newTestReconciler(t, modelDeployment)
	reconcileSuccessfully(t, reconciler, modelDeployment)

	deployment := getDeployment(t, counted, modelDeployment)
	deployment.Status.ObservedGeneration = deployment.Generation
	deployment.Status.Replicas = 1
	deployment.Status.UpdatedReplicas = 1
	deployment.Status.ReadyReplicas = 1
	deployment.Status.AvailableReplicas = 1
	if err := counted.Client.Status().Update(context.Background(), deployment); err != nil {
		t.Fatalf("update Deployment readiness: %v", err)
	}
	counted.resetCounts()

	reconcileSuccessfully(t, reconciler, modelDeployment)
	observed := getModelDeployment(t, counted, modelDeployment)
	if observed.Status.ActiveModel != "sentiment" || observed.Status.ActiveVersion != "v1" {
		t.Fatalf("active model = %s:%s, want sentiment:v1", observed.Status.ActiveModel, observed.Status.ActiveVersion)
	}
	assertCondition(t, observed, platformv1alpha1.ConditionAvailable, metav1.ConditionTrue, "MinimumReplicasAvailable")
	assertCondition(t, observed, platformv1alpha1.ConditionProgressing, metav1.ConditionFalse, "RolloutComplete")
}

func TestTransientChildFailureReturnsErrorAndSetsDegraded(t *testing.T) {
	modelDeployment := validModelDeployment()
	reconciler, counted := newTestReconciler(t, modelDeployment)
	counted.failDeploymentCreate = true

	_, err := reconciler.Reconcile(context.Background(), requestFor(modelDeployment))
	if err == nil {
		t.Fatal("transient child failure did not return an error")
	}
	observed := getModelDeployment(t, counted, modelDeployment)
	assertCondition(t, observed, platformv1alpha1.ConditionDegraded, metav1.ConditionTrue, "DeploymentReconcileFailed")
	if observed.Status.ObservedGeneration != 0 {
		t.Fatalf("failed reconciliation advanced observed generation to %d", observed.Status.ObservedGeneration)
	}
}

func TestControllerRefusesToAdoptUnrelatedChild(t *testing.T) {
	modelDeployment := validModelDeployment()
	unrelated := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{
		Name:            modelDeployment.Name,
		Namespace:       modelDeployment.Namespace,
		ResourceVersion: "1",
	}}
	reconciler, counted := newTestReconciler(t, modelDeployment, unrelated)

	_, err := reconciler.Reconcile(context.Background(), requestFor(modelDeployment))
	if err == nil {
		t.Fatal("unrelated child collision did not return an error")
	}
	observed := getModelDeployment(t, counted, modelDeployment)
	assertCondition(t, observed, platformv1alpha1.ConditionDegraded, metav1.ConditionTrue, "DeploymentReconcileFailed")
}

func TestDeletedResourceNeedsNoFinalizerCleanup(t *testing.T) {
	modelDeployment := validModelDeployment()
	reconciler, counted := newTestReconciler(t, modelDeployment)
	reconcileSuccessfully(t, reconciler, modelDeployment)
	if err := counted.Client.Delete(context.Background(), modelDeployment); err != nil {
		t.Fatalf("delete ModelDeployment: %v", err)
	}

	if _, err := reconciler.Reconcile(context.Background(), requestFor(modelDeployment)); err != nil {
		t.Fatalf("reconcile deleted resource: %v", err)
	}
}

func validModelDeployment() *platformv1alpha1.ModelDeployment {
	replicas := int32(1)
	return &platformv1alpha1.ModelDeployment{
		TypeMeta: metav1.TypeMeta{
			APIVersion: platformv1alpha1.GroupVersion.String(),
			Kind:       "ModelDeployment",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:       "sentiment",
			Namespace:  "default",
			UID:        types.UID("test-model-deployment"),
			Generation: 3,
		},
		Spec: platformv1alpha1.ModelDeploymentSpec{
			Model: platformv1alpha1.ModelReference{Name: "sentiment", Version: "v1"},
			Runtime: platformv1alpha1.RuntimeSpec{
				Image: "kernexys/model-runtime:v1",
				Port:  8080,
			},
			Replicas: &replicas,
		},
	}
}

func newTestReconciler(
	t *testing.T,
	objects ...client.Object,
) (*ModelDeploymentReconciler, *countingClient) {
	t.Helper()
	scheme := runtime.NewScheme()
	if err := appsv1.AddToScheme(scheme); err != nil {
		t.Fatalf("register apps scheme: %v", err)
	}
	if err := corev1.AddToScheme(scheme); err != nil {
		t.Fatalf("register core scheme: %v", err)
	}
	if err := platformv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatalf("register platform scheme: %v", err)
	}
	base := fake.NewClientBuilder().
		WithScheme(scheme).
		WithStatusSubresource(&platformv1alpha1.ModelDeployment{}, &appsv1.Deployment{}).
		WithObjects(objects...).
		Build()
	counted := &countingClient{Client: base}
	return &ModelDeploymentReconciler{Client: counted, Scheme: scheme}, counted
}

func reconcileSuccessfully(
	t *testing.T,
	reconciler *ModelDeploymentReconciler,
	modelDeployment *platformv1alpha1.ModelDeployment,
) {
	t.Helper()
	result, err := reconciler.Reconcile(context.Background(), requestFor(modelDeployment))
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if result != (ctrl.Result{}) {
		t.Fatalf("result = %#v, want empty result", result)
	}
}

func requestFor(modelDeployment *platformv1alpha1.ModelDeployment) ctrl.Request {
	return ctrl.Request{NamespacedName: namespacedName(modelDeployment)}
}

func getModelDeployment(
	t *testing.T,
	client client.Client,
	modelDeployment *platformv1alpha1.ModelDeployment,
) *platformv1alpha1.ModelDeployment {
	t.Helper()
	value := &platformv1alpha1.ModelDeployment{}
	if err := client.Get(context.Background(), namespacedName(modelDeployment), value); err != nil {
		t.Fatalf("get ModelDeployment: %v", err)
	}
	return value
}

func getDeployment(t *testing.T, client client.Client, modelDeployment *platformv1alpha1.ModelDeployment) *appsv1.Deployment {
	t.Helper()
	value := &appsv1.Deployment{}
	if err := client.Get(context.Background(), namespacedName(modelDeployment), value); err != nil {
		t.Fatalf("get Deployment: %v", err)
	}
	return value
}

func getService(t *testing.T, client client.Client, modelDeployment *platformv1alpha1.ModelDeployment) *corev1.Service {
	t.Helper()
	value := &corev1.Service{}
	if err := client.Get(context.Background(), namespacedName(modelDeployment), value); err != nil {
		t.Fatalf("get Service: %v", err)
	}
	return value
}

func assertCondition(
	t *testing.T,
	modelDeployment *platformv1alpha1.ModelDeployment,
	conditionType string,
	wantStatus metav1.ConditionStatus,
	wantReason string,
) {
	t.Helper()
	condition := meta.FindStatusCondition(modelDeployment.Status.Conditions, conditionType)
	if condition == nil {
		t.Fatalf("condition %q is missing", conditionType)
	}
	if condition.Status != wantStatus || condition.Reason != wantReason {
		t.Fatalf(
			"condition %q = status %s reason %s, want %s/%s",
			conditionType,
			condition.Status,
			condition.Reason,
			wantStatus,
			wantReason,
		)
	}
	if condition.ObservedGeneration != modelDeployment.Generation {
		t.Fatalf(
			"condition %q observed generation = %d, want %d",
			conditionType,
			condition.ObservedGeneration,
			modelDeployment.Generation,
		)
	}
}

type countingClient struct {
	client.Client
	creates              int
	updates              int
	statusUpdates        int
	failDeploymentCreate bool
}

func (c *countingClient) Create(ctx context.Context, object client.Object, options ...client.CreateOption) error {
	if c.failDeploymentCreate {
		if _, isDeployment := object.(*appsv1.Deployment); isDeployment {
			return errors.New("simulated API server outage")
		}
	}
	c.creates++
	return c.Client.Create(ctx, object, options...)
}

func (c *countingClient) Update(ctx context.Context, object client.Object, options ...client.UpdateOption) error {
	c.updates++
	return c.Client.Update(ctx, object, options...)
}

func (c *countingClient) Status() client.SubResourceWriter {
	return &countingStatusWriter{SubResourceWriter: c.Client.Status(), parent: c}
}

func (c *countingClient) resetCounts() {
	c.creates = 0
	c.updates = 0
	c.statusUpdates = 0
}

type countingStatusWriter struct {
	client.SubResourceWriter
	parent *countingClient
}

func (w *countingStatusWriter) Update(
	ctx context.Context,
	object client.Object,
	options ...client.SubResourceUpdateOption,
) error {
	w.parent.statusUpdates++
	return w.SubResourceWriter.Update(ctx, object, options...)
}
