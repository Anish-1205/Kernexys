// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

const (
	ConditionAvailable   = "Available"
	ConditionProgressing = "Progressing"
	ConditionDegraded    = "Degraded"
)

type ModelReference struct {
	// Name identifies the registered model.
	// +kubebuilder:validation:MinLength=1
	// +kubebuilder:validation:MaxLength=63
	// +kubebuilder:validation:Pattern=`^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$`
	Name string `json:"name"`

	// Version identifies an immutable registered model version.
	// +kubebuilder:validation:MinLength=1
	// +kubebuilder:validation:MaxLength=63
	// +kubebuilder:validation:Pattern=`^[A-Za-z0-9](?:[-._A-Za-z0-9]*[A-Za-z0-9])?$`
	Version string `json:"version"`
}

type RuntimeSpec struct {
	// Image is the OCI image containing the model runtime and artifact.
	// +kubebuilder:validation:MinLength=1
	// +kubebuilder:validation:MaxLength=512
	Image string `json:"image"`

	// Port is the HTTP port exposed by the model runtime.
	// +kubebuilder:default=8080
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	Port int32 `json:"port,omitempty"`
}

type RuntimeResources struct {
	// Limits defines the maximum compute resources available to a runtime.
	Limits corev1.ResourceList `json:"limits,omitempty"`

	// Requests defines the compute resources reserved for a runtime.
	Requests corev1.ResourceList `json:"requests,omitempty"`
}

type ModelDeploymentSpec struct {
	Model ModelReference `json:"model"`

	Runtime RuntimeSpec `json:"runtime"`

	// Replicas is the fixed desired replica count for the synchronous runtime.
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=100
	Replicas *int32 `json:"replicas,omitempty"`

	// Resources defines container requests and limits.
	Resources RuntimeResources `json:"resources,omitempty"`
}

type ModelDeploymentStatus struct {
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`

	DesiredReplicas int32 `json:"desiredReplicas,omitempty"`

	ReadyReplicas int32 `json:"readyReplicas,omitempty"`

	ActiveModel string `json:"activeModel,omitempty"`

	ActiveVersion string `json:"activeVersion,omitempty"`

	Endpoint string `json:"endpoint,omitempty"`

	// +listType=map
	// +listMapKey=type
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=md
// +kubebuilder:printcolumn:name="Model",type=string,JSONPath=`.spec.model.name`
// +kubebuilder:printcolumn:name="Version",type=string,JSONPath=`.spec.model.version`
// +kubebuilder:printcolumn:name="Ready",type=integer,JSONPath=`.status.readyReplicas`
// +kubebuilder:printcolumn:name="Desired",type=integer,JSONPath=`.status.desiredReplicas`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`
type ModelDeployment struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ModelDeploymentSpec   `json:"spec,omitempty"`
	Status ModelDeploymentStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true
type ModelDeploymentList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ModelDeployment `json:"items"`
}
