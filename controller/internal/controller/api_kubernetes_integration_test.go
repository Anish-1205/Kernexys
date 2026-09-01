// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

//go:build integration

package controller

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
	clientcmdapi "k8s.io/client-go/tools/clientcmd/api"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
)

func TestAPIKubernetesBridgeAgainstAPIServer(t *testing.T) {
	if os.Getenv("KUBEBUILDER_ASSETS") == "" {
		t.Skip("KUBEBUILDER_ASSETS is not set; run make api-kubernetes-integration")
	}
	python := os.Getenv("KERNEXYS_TEST_PYTHON")
	if python == "" {
		t.Skip("KERNEXYS_TEST_PYTHON is not set; run make api-kubernetes-integration")
	}

	environment := &envtest.Environment{
		CRDDirectoryPaths: []string{filepath.Join("..", "..", "config", "crd", "bases")},
	}
	restConfig, err := environment.Start()
	if err != nil {
		t.Fatalf("start envtest: %v", err)
	}
	t.Cleanup(func() { stopTestEnvironment(t, environment) })
	clientset, err := kubernetes.NewForConfig(restConfig)
	if err != nil {
		t.Fatalf("create envtest Kubernetes client: %v", err)
	}
	if _, err := clientset.CoreV1().Namespaces().Create(
		context.Background(),
		&corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "api-integration"}},
		metav1.CreateOptions{},
	); err != nil {
		t.Fatalf("create API integration namespace: %v", err)
	}

	kubeconfig := clientcmdapi.Config{
		Clusters: map[string]*clientcmdapi.Cluster{
			"envtest": {
				Server:                   restConfig.Host,
				CertificateAuthorityData: restConfig.CAData,
			},
		},
		AuthInfos: map[string]*clientcmdapi.AuthInfo{
			"envtest": {
				ClientCertificateData: restConfig.CertData,
				ClientKeyData:         restConfig.KeyData,
			},
		},
		Contexts: map[string]*clientcmdapi.Context{
			"envtest": {Cluster: "envtest", AuthInfo: "envtest"},
		},
		CurrentContext: "envtest",
	}
	contents, err := clientcmd.Write(kubeconfig)
	if err != nil {
		t.Fatalf("serialize envtest kubeconfig: %v", err)
	}
	kubeconfigPath := filepath.Join(t.TempDir(), "kubeconfig")
	if err := os.WriteFile(kubeconfigPath, contents, 0o600); err != nil {
		t.Fatalf("write envtest kubeconfig: %v", err)
	}

	repositoryRoot, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatalf("resolve repository root: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	command := exec.CommandContext(
		ctx,
		python,
		"-m",
		"pytest",
		filepath.Join(repositoryRoot, "tests", "integration", "test_api_kubernetes.py"),
		"--basetemp="+filepath.Join(repositoryRoot, ".test-tmp", "api-kubernetes"),
		"-q",
	)
	command.Dir = repositoryRoot
	command.Env = append(os.Environ(), "KERNEXYS_TEST_KUBECONFIG="+kubeconfigPath)
	output, err := command.CombinedOutput()
	if ctx.Err() != nil {
		t.Fatalf("Python API/Kubernetes integration timed out: %v\n%s", ctx.Err(), output)
	}
	if err != nil {
		t.Fatalf("Python API/Kubernetes integration failed: %v\n%s", err, output)
	}
	t.Logf("Python API/Kubernetes integration output:\n%s", output)
}
