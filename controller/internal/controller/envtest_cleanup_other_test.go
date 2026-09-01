// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

//go:build !windows

package controller

import "sigs.k8s.io/controller-runtime/pkg/envtest"

func recoverEnvtestStop(_ *envtest.Environment, _ error) (bool, error) {
	return false, nil
}
