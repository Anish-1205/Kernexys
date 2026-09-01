// Copyright 2026 The Kernexys Authors.
// SPDX-License-Identifier: Apache-2.0

//go:build windows

package controller

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"unsafe"

	"golang.org/x/sys/windows"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
)

const envtestProcessExitCode = 1

func recoverEnvtestStop(environment *envtest.Environment, stopErr error) (bool, error) {
	message := stopErr.Error()
	if !strings.Contains(message, "not supported by windows") ||
		(!strings.Contains(message, "kube-apiserver") && !strings.Contains(message, "etcd")) {
		return false, nil
	}

	targets := map[string]struct{}{}
	for _, path := range []string{
		environment.ControlPlane.GetAPIServer().Path,
		environment.ControlPlane.Etcd.Path,
	} {
		absolutePath, err := filepath.Abs(path)
		if err != nil {
			return true, fmt.Errorf("resolve envtest process path %q: %w", path, err)
		}
		targets[normalizeWindowsPath(absolutePath)] = struct{}{}
	}

	if err := terminateExactProcesses(targets); err != nil {
		return true, err
	}
	return true, nil
}

func terminateExactProcesses(targets map[string]struct{}) error {
	snapshot, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPPROCESS, 0)
	if err != nil {
		return fmt.Errorf("snapshot Windows processes: %w", err)
	}
	defer windows.CloseHandle(snapshot)

	targetNames := make(map[string]struct{}, len(targets))
	for path := range targets {
		targetNames[strings.ToLower(filepath.Base(path))] = struct{}{}
	}

	entry := windows.ProcessEntry32{Size: uint32(unsafe.Sizeof(windows.ProcessEntry32{}))}
	if err := windows.Process32First(snapshot, &entry); err != nil {
		if errors.Is(err, windows.ERROR_NO_MORE_FILES) {
			return nil
		}
		return fmt.Errorf("read first Windows process: %w", err)
	}

	for {
		name := strings.ToLower(windows.UTF16ToString(entry.ExeFile[:]))
		if _, relevant := targetNames[name]; relevant {
			if err := terminateProcessIfExact(entry.ProcessID, targets); err != nil {
				return err
			}
		}

		err := windows.Process32Next(snapshot, &entry)
		if errors.Is(err, windows.ERROR_NO_MORE_FILES) {
			return nil
		}
		if err != nil {
			return fmt.Errorf("read next Windows process: %w", err)
		}
	}
}

func terminateProcessIfExact(processID uint32, targets map[string]struct{}) error {
	handle, err := windows.OpenProcess(
		windows.PROCESS_QUERY_LIMITED_INFORMATION|windows.PROCESS_TERMINATE|windows.SYNCHRONIZE,
		false,
		processID,
	)
	if err != nil {
		return fmt.Errorf("open candidate envtest process %d: %w", processID, err)
	}
	defer windows.CloseHandle(handle)

	buffer := make([]uint16, 32768)
	length := uint32(len(buffer))
	if err := windows.QueryFullProcessImageName(handle, 0, &buffer[0], &length); err != nil {
		return fmt.Errorf("resolve candidate envtest process %d: %w", processID, err)
	}
	path := normalizeWindowsPath(windows.UTF16ToString(buffer[:length]))
	if _, exact := targets[path]; !exact {
		return nil
	}

	if err := windows.TerminateProcess(handle, envtestProcessExitCode); err != nil {
		return fmt.Errorf("terminate envtest process %d at %q: %w", processID, path, err)
	}
	event, err := windows.WaitForSingleObject(handle, 5000)
	if err != nil {
		return fmt.Errorf("wait for envtest process %d at %q: %w", processID, path, err)
	}
	if event == uint32(windows.WAIT_TIMEOUT) {
		return fmt.Errorf("timed out waiting for envtest process %d at %q", processID, path)
	}
	return nil
}

func normalizeWindowsPath(path string) string {
	normalized := strings.ToLower(strings.TrimPrefix(filepath.Clean(path), `\\?\`))
	if filepath.Ext(normalized) == "" {
		normalized += ".exe"
	}
	return normalized
}
