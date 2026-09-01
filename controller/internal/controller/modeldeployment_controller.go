// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

package controller

import (
	"context"
	"errors"
	"fmt"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/equality"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	controlleroptions "sigs.k8s.io/controller-runtime/pkg/controller"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	platformv1alpha1 "github.com/kernexys/kernexys/controller/api/v1alpha1"
)

const (
	managedByLabel = "app.kubernetes.io/managed-by"
	instanceLabel  = "app.kubernetes.io/instance"
	nameLabel      = "app.kubernetes.io/name"

	managedByValue = "kernexys-controller"
	runtimeName    = "model-runtime"
	defaultPort    = int32(8080)
)

// ModelDeploymentReconciler converges controller-owned workloads to ModelDeployment specs.
type ModelDeploymentReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=platform.kernexys.io,resources=modeldeployments,verbs=get;list;watch
// +kubebuilder:rbac:groups=platform.kernexys.io,resources=modeldeployments/status,verbs=get;patch;update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=create;get;list;patch;update;watch
// +kubebuilder:rbac:groups="",resources=services,verbs=create;get;list;patch;update;watch

func (r *ModelDeploymentReconciler) Reconcile(ctx context.Context, request ctrl.Request) (ctrl.Result, error) {
	logger := logf.FromContext(ctx).WithValues("modelDeployment", request.NamespacedName)
	modelDeployment := &platformv1alpha1.ModelDeployment{}
	if err := r.Get(ctx, request.NamespacedName, modelDeployment); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}
	if !modelDeployment.DeletionTimestamp.IsZero() {
		return ctrl.Result{}, nil
	}

	if err := validateSpec(modelDeployment); err != nil {
		logger.Info("desired state is invalid", "error", err)
		return ctrl.Result{}, r.updateInvalidStatus(ctx, modelDeployment, err)
	}

	deployment := desiredDeployment(modelDeployment)
	if _, err := controllerutil.CreateOrUpdate(ctx, r.Client, deployment, func() error {
		if err := r.ensureControllerOwnership(modelDeployment, deployment); err != nil {
			return err
		}
		mutateDeployment(modelDeployment, deployment)
		return nil
	}); err != nil {
		return ctrl.Result{}, r.reconcileError(ctx, modelDeployment, "DeploymentReconcileFailed", err)
	}

	service := desiredService(modelDeployment)
	if _, err := controllerutil.CreateOrUpdate(ctx, r.Client, service, func() error {
		if err := r.ensureControllerOwnership(modelDeployment, service); err != nil {
			return err
		}
		mutateService(modelDeployment, service)
		return nil
	}); err != nil {
		return ctrl.Result{}, r.reconcileError(ctx, modelDeployment, "ServiceReconcileFailed", err)
	}

	if err := r.updateObservedStatus(ctx, modelDeployment, deployment, service); err != nil {
		return ctrl.Result{}, fmt.Errorf("update ModelDeployment status: %w", err)
	}

	logger.Info(
		"reconciliation complete",
		"readyReplicas", deployment.Status.ReadyReplicas,
		"desiredReplicas", desiredReplicaCount(modelDeployment),
	)
	return ctrl.Result{}, nil
}

func (r *ModelDeploymentReconciler) SetupWithManager(manager ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(manager).
		For(&platformv1alpha1.ModelDeployment{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		WithOptions(controlleroptions.Options{MaxConcurrentReconciles: 4}).
		Complete(r)
}

func (r *ModelDeploymentReconciler) ensureControllerOwnership(
	owner *platformv1alpha1.ModelDeployment,
	object client.Object,
) error {
	existingOwner := metav1.GetControllerOf(object)
	if object.GetResourceVersion() != "" && existingOwner == nil {
		return fmt.Errorf(
			"refusing to adopt existing %T %s/%s without a controller owner",
			object,
			object.GetNamespace(),
			object.GetName(),
		)
	}
	return controllerutil.SetControllerReference(owner, object, r.Scheme)
}

func (r *ModelDeploymentReconciler) updateInvalidStatus(
	ctx context.Context,
	modelDeployment *platformv1alpha1.ModelDeployment,
	validationError error,
) error {
	desired := modelDeployment.Status
	desired.ObservedGeneration = modelDeployment.Generation
	desired.DesiredReplicas = desiredReplicaCount(modelDeployment)
	setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionAvailable, metav1.ConditionFalse, "InvalidSpec", "Desired state is invalid.")
	setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionProgressing, metav1.ConditionFalse, "InvalidSpec", "Reconciliation is paused until the desired state is corrected.")
	setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionDegraded, metav1.ConditionTrue, "InvalidSpec", validationError.Error())
	return r.updateStatusIfChanged(ctx, modelDeployment, desired)
}

func (r *ModelDeploymentReconciler) reconcileError(
	ctx context.Context,
	modelDeployment *platformv1alpha1.ModelDeployment,
	reason string,
	reconcileError error,
) error {
	desired := modelDeployment.Status
	setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionAvailable, metav1.ConditionFalse, reason, "The desired workload could not be reconciled.")
	setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionProgressing, metav1.ConditionFalse, reason, "controller-runtime will retry the transient failure.")
	setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionDegraded, metav1.ConditionTrue, reason, reconcileError.Error())
	statusError := r.updateStatusIfChanged(ctx, modelDeployment, desired)
	return errors.Join(reconcileError, statusError)
}

func (r *ModelDeploymentReconciler) updateObservedStatus(
	ctx context.Context,
	modelDeployment *platformv1alpha1.ModelDeployment,
	deployment *appsv1.Deployment,
	service *corev1.Service,
) error {
	desiredReplicas := desiredReplicaCount(modelDeployment)
	ready := deployment.Status.ReadyReplicas
	available := deployment.Status.ObservedGeneration == deployment.Generation &&
		deployment.Status.UpdatedReplicas == desiredReplicas &&
		deployment.Status.AvailableReplicas == desiredReplicas &&
		ready == desiredReplicas

	desired := modelDeployment.Status
	desired.ObservedGeneration = modelDeployment.Generation
	desired.DesiredReplicas = desiredReplicas
	desired.ReadyReplicas = ready
	desired.Endpoint = fmt.Sprintf("http://%s.%s.svc.cluster.local", service.Name, service.Namespace)
	if available {
		desired.ActiveModel = modelDeployment.Spec.Model.Name
		desired.ActiveVersion = modelDeployment.Spec.Model.Version
		setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionAvailable, metav1.ConditionTrue, "MinimumReplicasAvailable", "All desired runtime replicas are available.")
		setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionProgressing, metav1.ConditionFalse, "RolloutComplete", "The runtime rollout is complete.")
	} else {
		message := fmt.Sprintf("Waiting for ready replicas: %d/%d.", ready, desiredReplicas)
		setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionAvailable, metav1.ConditionFalse, "ReplicasNotReady", message)
		setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionProgressing, metav1.ConditionTrue, "Reconciling", message)
	}
	setCondition(&desired, modelDeployment.Generation, platformv1alpha1.ConditionDegraded, metav1.ConditionFalse, "ReconcileSucceeded", "The desired child resources were reconciled.")
	return r.updateStatusIfChanged(ctx, modelDeployment, desired)
}

func (r *ModelDeploymentReconciler) updateStatusIfChanged(
	ctx context.Context,
	modelDeployment *platformv1alpha1.ModelDeployment,
	desired platformv1alpha1.ModelDeploymentStatus,
) error {
	if equality.Semantic.DeepEqual(modelDeployment.Status, desired) {
		return nil
	}
	modelDeployment.Status = desired
	if err := r.Status().Update(ctx, modelDeployment); err != nil {
		if apierrors.IsConflict(err) {
			return fmt.Errorf("status update conflict: %w", err)
		}
		return err
	}
	return nil
}

func setCondition(
	status *platformv1alpha1.ModelDeploymentStatus,
	observedGeneration int64,
	conditionType string,
	conditionStatus metav1.ConditionStatus,
	reason string,
	message string,
) {
	meta.SetStatusCondition(&status.Conditions, metav1.Condition{
		Type:               conditionType,
		Status:             conditionStatus,
		ObservedGeneration: observedGeneration,
		Reason:             reason,
		Message:            message,
	})
}

func validateSpec(modelDeployment *platformv1alpha1.ModelDeployment) error {
	if strings.TrimSpace(modelDeployment.Spec.Model.Name) == "" {
		return errors.New("spec.model.name must not be empty")
	}
	if strings.TrimSpace(modelDeployment.Spec.Model.Version) == "" {
		return errors.New("spec.model.version must not be empty")
	}
	if strings.TrimSpace(modelDeployment.Spec.Runtime.Image) == "" || strings.ContainsAny(modelDeployment.Spec.Runtime.Image, " \t\r\n") {
		return errors.New("spec.runtime.image must be a non-empty OCI image reference without whitespace")
	}
	replicas := desiredReplicaCount(modelDeployment)
	if replicas < 1 || replicas > 100 {
		return fmt.Errorf("spec.replicas must be between 1 and 100, got %d", replicas)
	}
	port := desiredRuntimePort(modelDeployment)
	if port < 1 || port > 65535 {
		return fmt.Errorf("spec.runtime.port must be between 1 and 65535, got %d", port)
	}
	for name, request := range modelDeployment.Spec.Resources.Requests {
		if request.Sign() < 0 {
			return fmt.Errorf("resource request %s must not be negative", name)
		}
		if limit, found := modelDeployment.Spec.Resources.Limits[name]; found && request.Cmp(limit) > 0 {
			return fmt.Errorf("resource request %s must not exceed its limit", name)
		}
	}
	for name, limit := range modelDeployment.Spec.Resources.Limits {
		if limit.Sign() < 0 {
			return fmt.Errorf("resource limit %s must not be negative", name)
		}
	}
	return nil
}

func desiredReplicaCount(modelDeployment *platformv1alpha1.ModelDeployment) int32 {
	if modelDeployment.Spec.Replicas == nil {
		return 1
	}
	return *modelDeployment.Spec.Replicas
}

func desiredRuntimePort(modelDeployment *platformv1alpha1.ModelDeployment) int32 {
	if modelDeployment.Spec.Runtime.Port == 0 {
		return defaultPort
	}
	return modelDeployment.Spec.Runtime.Port
}

func desiredDeployment(modelDeployment *platformv1alpha1.ModelDeployment) *appsv1.Deployment {
	return &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: modelDeployment.Name, Namespace: modelDeployment.Namespace}}
}

func mutateDeployment(modelDeployment *platformv1alpha1.ModelDeployment, deployment *appsv1.Deployment) {
	labels := childLabels(modelDeployment)
	replicas := desiredReplicaCount(modelDeployment)
	port := desiredRuntimePort(modelDeployment)
	terminationGracePeriod := int64(30)
	revisionHistoryLimit := int32(10)
	progressDeadlineSeconds := int32(600)
	runAsUser := int64(10001)
	runAsGroup := int64(10001)
	runAsNonRoot := true
	readOnlyRootFilesystem := true
	allowPrivilegeEscalation := false
	automountServiceAccountToken := false
	enableServiceLinks := false

	deployment.Labels = labels
	deployment.Spec = appsv1.DeploymentSpec{
		Replicas: &replicas,
		Selector: &metav1.LabelSelector{MatchLabels: labels},
		Strategy: appsv1.DeploymentStrategy{
			Type: appsv1.RollingUpdateDeploymentStrategyType,
			RollingUpdate: &appsv1.RollingUpdateDeployment{
				MaxUnavailable: intOrStringPointer(intstr.FromString("25%")),
				MaxSurge:       intOrStringPointer(intstr.FromString("25%")),
			},
		},
		RevisionHistoryLimit:    &revisionHistoryLimit,
		ProgressDeadlineSeconds: &progressDeadlineSeconds,
		Template: corev1.PodTemplateSpec{
			ObjectMeta: metav1.ObjectMeta{
				Labels: labels,
				Annotations: map[string]string{
					"platform.kernexys.io/model":   modelDeployment.Spec.Model.Name,
					"platform.kernexys.io/version": modelDeployment.Spec.Model.Version,
				},
			},
			Spec: corev1.PodSpec{
				AutomountServiceAccountToken:  &automountServiceAccountToken,
				EnableServiceLinks:            &enableServiceLinks,
				RestartPolicy:                 corev1.RestartPolicyAlways,
				DNSPolicy:                     corev1.DNSClusterFirst,
				SchedulerName:                 corev1.DefaultSchedulerName,
				TerminationGracePeriodSeconds: &terminationGracePeriod,
				SecurityContext: &corev1.PodSecurityContext{
					RunAsUser:    &runAsUser,
					RunAsGroup:   &runAsGroup,
					RunAsNonRoot: &runAsNonRoot,
					SeccompProfile: &corev1.SeccompProfile{
						Type: corev1.SeccompProfileTypeRuntimeDefault,
					},
				},
				Containers: []corev1.Container{{
					Name:                     runtimeName,
					Image:                    modelDeployment.Spec.Runtime.Image,
					ImagePullPolicy:          corev1.PullIfNotPresent,
					TerminationMessagePath:   corev1.TerminationMessagePathDefault,
					TerminationMessagePolicy: corev1.TerminationMessageReadFile,
					SecurityContext: &corev1.SecurityContext{
						AllowPrivilegeEscalation: &allowPrivilegeEscalation,
						ReadOnlyRootFilesystem:   &readOnlyRootFilesystem,
						RunAsNonRoot:             &runAsNonRoot,
						Capabilities: &corev1.Capabilities{
							Drop: []corev1.Capability{"ALL"},
						},
					},
					Env: []corev1.EnvVar{
						{Name: "KERNEXYS_MODEL_NAME", Value: modelDeployment.Spec.Model.Name},
						{Name: "KERNEXYS_MODEL_VERSION", Value: modelDeployment.Spec.Model.Version},
					},
					Ports: []corev1.ContainerPort{{Name: "http", ContainerPort: port, Protocol: corev1.ProtocolTCP}},
					Resources: corev1.ResourceRequirements{
						Limits:   modelDeployment.Spec.Resources.Limits.DeepCopy(),
						Requests: modelDeployment.Spec.Resources.Requests.DeepCopy(),
					},
					StartupProbe:   httpProbe("/health/ready", port, 30),
					LivenessProbe:  httpProbe("/health/live", port, 3),
					ReadinessProbe: httpProbe("/health/ready", port, 3),
				}},
			},
		},
	}
}

func desiredService(modelDeployment *platformv1alpha1.ModelDeployment) *corev1.Service {
	return &corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: modelDeployment.Name, Namespace: modelDeployment.Namespace}}
}

func mutateService(modelDeployment *platformv1alpha1.ModelDeployment, service *corev1.Service) {
	service.Labels = childLabels(modelDeployment)
	service.Spec.Type = corev1.ServiceTypeClusterIP
	service.Spec.Selector = childLabels(modelDeployment)
	service.Spec.SessionAffinity = corev1.ServiceAffinityNone
	service.Spec.Ports = []corev1.ServicePort{{
		Name:       "http",
		Protocol:   corev1.ProtocolTCP,
		Port:       80,
		TargetPort: intstr.FromString("http"),
	}}
}

func childLabels(modelDeployment *platformv1alpha1.ModelDeployment) map[string]string {
	return map[string]string{
		nameLabel:      runtimeName,
		instanceLabel:  modelDeployment.Name,
		managedByLabel: managedByValue,
	}
}

func httpProbe(path string, port int32, failureThreshold int32) *corev1.Probe {
	return &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{HTTPGet: &corev1.HTTPGetAction{
			Path:   path,
			Port:   intstr.FromInt32(port),
			Scheme: corev1.URISchemeHTTP,
		}},
		InitialDelaySeconds: 0,
		TimeoutSeconds:      1,
		PeriodSeconds:       10,
		SuccessThreshold:    1,
		FailureThreshold:    failureThreshold,
	}
}

func intOrStringPointer(value intstr.IntOrString) *intstr.IntOrString {
	return &value
}

func namespacedName(modelDeployment *platformv1alpha1.ModelDeployment) types.NamespacedName {
	return types.NamespacedName{Name: modelDeployment.Name, Namespace: modelDeployment.Namespace}
}
