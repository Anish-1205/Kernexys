// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"flag"
	"os"
	"time"

	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	platformv1alpha1 "github.com/Anish-1205/Kernexys/controller/api/v1alpha1"
	kernexyscontroller "github.com/Anish-1205/Kernexys/controller/internal/controller"
)

func main() {
	var metricsAddress string
	var probeAddress string
	var enableLeaderElection bool
	flag.StringVar(&metricsAddress, "metrics-bind-address", ":8080", "Address for Prometheus metrics.")
	flag.StringVar(&probeAddress, "health-probe-bind-address", ":8081", "Address for health probes.")
	flag.BoolVar(&enableLeaderElection, "leader-elect", false, "Enable leader election.")

	logOptions := zap.Options{Development: false}
	logOptions.BindFlags(flag.CommandLine)
	flag.Parse()
	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&logOptions)))
	logger := ctrl.Log.WithName("setup")

	scheme := clientgoscheme.Scheme
	if err := platformv1alpha1.AddToScheme(scheme); err != nil {
		logger.Error(err, "unable to register Kernexys API types")
		os.Exit(1)
	}

	gracefulShutdownTimeout := 20 * time.Second
	manager, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
		Scheme:                        scheme,
		Metrics:                       metricsserver.Options{BindAddress: metricsAddress},
		HealthProbeBindAddress:        probeAddress,
		LeaderElection:                enableLeaderElection,
		LeaderElectionID:              "controller.platform.kernexys.io",
		LeaderElectionNamespace:       "kernexys-system",
		GracefulShutdownTimeout:       &gracefulShutdownTimeout,
		LeaderElectionReleaseOnCancel: true,
	})
	if err != nil {
		logger.Error(err, "unable to create manager")
		os.Exit(1)
	}

	reconciler := &kernexyscontroller.ModelDeploymentReconciler{
		Client: manager.GetClient(),
		Scheme: manager.GetScheme(),
	}
	if err := reconciler.SetupWithManager(manager); err != nil {
		logger.Error(err, "unable to create ModelDeployment controller")
		os.Exit(1)
	}
	if err := manager.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		logger.Error(err, "unable to register liveness check")
		os.Exit(1)
	}
	if err := manager.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		logger.Error(err, "unable to register readiness check")
		os.Exit(1)
	}

	logger.Info("starting manager")
	if err := manager.Start(ctrl.SetupSignalHandler()); err != nil {
		logger.Error(err, "manager stopped with an error")
		os.Exit(1)
	}
}
