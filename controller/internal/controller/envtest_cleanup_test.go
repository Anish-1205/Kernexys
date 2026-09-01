// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

package controller

import (
	"testing"

	"sigs.k8s.io/controller-runtime/pkg/envtest"
)

func stopTestEnvironment(t *testing.T, environment *envtest.Environment) {
	t.Helper()

	stopErr := environment.Stop()
	if stopErr == nil {
		return
	}

	handled, recoveryErr := recoverEnvtestStop(environment, stopErr)
	if !handled {
		t.Errorf("stop envtest: %v", stopErr)
		return
	}
	if recoveryErr != nil {
		t.Errorf("stop envtest after controller-runtime shutdown failure %q: %v", stopErr, recoveryErr)
		return
	}

	t.Logf("controller-runtime could not use Unix termination signals on Windows; terminated the exact envtest processes instead: %v", stopErr)
}
