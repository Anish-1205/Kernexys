// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

package controller

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"

	platformv1alpha1 "github.com/Anish-1205/Kernexys/controller/api/v1alpha1"
)

func TestEnvtestReconciliationAgainstAPIServer(t *testing.T) {
	if os.Getenv("KUBEBUILDER_ASSETS") == "" {
		t.Skip("KUBEBUILDER_ASSETS is not set; run make controller-integration")
	}

	environment := &envtest.Environment{
		CRDDirectoryPaths: []string{filepath.Join("..", "..", "config", "crd", "bases")},
	}
	config, err := environment.Start()
	if err != nil {
		t.Fatalf("start envtest: %v", err)
	}
	t.Cleanup(func() { stopTestEnvironment(t, environment) })

	scheme := runtime.NewScheme()
	for name, register := range map[string]func(*runtime.Scheme) error{
		"apps":     appsv1.AddToScheme,
		"core":     corev1.AddToScheme,
		"platform": platformv1alpha1.AddToScheme,
	} {
		if err := register(scheme); err != nil {
			t.Fatalf("register %s scheme: %v", name, err)
		}
	}
	apiClient, err := client.New(config, client.Options{Scheme: scheme})
	if err != nil {
		t.Fatalf("create API client: %v", err)
	}
	ctx := context.Background()
	if err := apiClient.Create(ctx, &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "envtest"}}); err != nil {
		t.Fatalf("create test namespace: %v", err)
	}

	modelDeployment := validModelDeployment()
	modelDeployment.Namespace = "envtest"
	modelDeployment.UID = ""
	modelDeployment.ResourceVersion = ""
	modelDeployment.Generation = 0
	modelDeployment.Spec.Replicas = nil
	modelDeployment.Spec.Runtime.Port = 0
	if err := apiClient.Create(ctx, modelDeployment); err != nil {
		t.Fatalf("create ModelDeployment: %v", err)
	}
	if modelDeployment.Spec.Replicas == nil || *modelDeployment.Spec.Replicas != 1 {
		t.Fatalf("CRD default replicas = %v, want 1", modelDeployment.Spec.Replicas)
	}
	if modelDeployment.Spec.Runtime.Port != 8080 {
		t.Fatalf("CRD default runtime port = %d, want 8080", modelDeployment.Spec.Runtime.Port)
	}

	reconciler := &ModelDeploymentReconciler{Client: apiClient, Scheme: scheme}
	reconcileSuccessfully(t, reconciler, modelDeployment)
	key := types.NamespacedName{Name: modelDeployment.Name, Namespace: modelDeployment.Namespace}
	firstDeployment := &appsv1.Deployment{}
	firstService := &corev1.Service{}
	firstStatus := &platformv1alpha1.ModelDeployment{}
	mustGet(t, apiClient, key, firstDeployment)
	mustGet(t, apiClient, key, firstService)
	mustGet(t, apiClient, key, firstStatus)
	if !metav1.IsControlledBy(firstDeployment, firstStatus) || !metav1.IsControlledBy(firstService, firstStatus) {
		t.Fatal("envtest children do not have ModelDeployment controller references")
	}

	deploymentResourceVersion := firstDeployment.ResourceVersion
	serviceResourceVersion := firstService.ResourceVersion
	statusResourceVersion := firstStatus.ResourceVersion
	reconcileSuccessfully(t, reconciler, modelDeployment)
	afterRepeatDeployment := &appsv1.Deployment{}
	afterRepeatService := &corev1.Service{}
	afterRepeatStatus := &platformv1alpha1.ModelDeployment{}
	mustGet(t, apiClient, key, afterRepeatDeployment)
	mustGet(t, apiClient, key, afterRepeatService)
	mustGet(t, apiClient, key, afterRepeatStatus)
	if afterRepeatDeployment.ResourceVersion != deploymentResourceVersion {
		t.Fatalf("repeated reconcile updated Deployment resourceVersion %s -> %s", deploymentResourceVersion, afterRepeatDeployment.ResourceVersion)
	}
	if afterRepeatService.ResourceVersion != serviceResourceVersion {
		t.Fatalf("repeated reconcile updated Service resourceVersion %s -> %s", serviceResourceVersion, afterRepeatService.ResourceVersion)
	}
	if afterRepeatStatus.ResourceVersion != statusResourceVersion {
		t.Fatalf("repeated reconcile updated status resourceVersion %s -> %s", statusResourceVersion, afterRepeatStatus.ResourceVersion)
	}

	replicas := int32(7)
	afterRepeatDeployment.Spec.Replicas = &replicas
	afterRepeatDeployment.Spec.Template.Spec.Containers[0].Image = "manual/drift:latest"
	if err := apiClient.Update(ctx, afterRepeatDeployment); err != nil {
		t.Fatalf("introduce envtest drift: %v", err)
	}
	reconcileSuccessfully(t, reconciler, modelDeployment)
	repaired := &appsv1.Deployment{}
	mustGet(t, apiClient, key, repaired)
	if *repaired.Spec.Replicas != 1 || repaired.Spec.Template.Spec.Containers[0].Image != "kernexys/model-runtime:v1" {
		t.Fatal("envtest reconciliation did not repair Deployment drift")
	}

	repaired.Status.ObservedGeneration = repaired.Generation
	repaired.Status.Replicas = 1
	repaired.Status.UpdatedReplicas = 1
	repaired.Status.ReadyReplicas = 1
	repaired.Status.AvailableReplicas = 1
	if err := apiClient.Status().Update(ctx, repaired); err != nil {
		t.Fatalf("set envtest Deployment ready: %v", err)
	}
	reconcileSuccessfully(t, reconciler, modelDeployment)
	readyStatus := &platformv1alpha1.ModelDeployment{}
	mustGet(t, apiClient, key, readyStatus)
	available := meta.FindStatusCondition(readyStatus.Status.Conditions, platformv1alpha1.ConditionAvailable)
	if available == nil || available.Status != metav1.ConditionTrue || readyStatus.Status.ActiveVersion != "v1" {
		t.Fatalf("ready status not observed: %#v", readyStatus.Status)
	}

	invalid := validModelDeployment()
	invalid.Name = "invalid"
	invalid.Namespace = "envtest"
	invalid.UID = ""
	zero := int32(0)
	invalid.Spec.Replicas = &zero
	if err := apiClient.Create(ctx, invalid); !apierrors.IsInvalid(err) {
		t.Fatalf("invalid CRD create error = %v, want Kubernetes Invalid", err)
	}
}

func mustGet(t *testing.T, apiClient client.Client, key types.NamespacedName, object client.Object) {
	t.Helper()
	if err := apiClient.Get(context.Background(), key, object); err != nil {
		t.Fatalf("get %T %s: %v", object, key, err)
	}
}
