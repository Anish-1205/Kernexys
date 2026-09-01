.PHONY: install format lint test migrate run container-build container-up container-down container-clean controller-generate controller-format controller-vet controller-test controller-integration api-kubernetes-integration runtime-install runtime-format runtime-lint runtime-test kind-create kind-delete kind-build kind-load kind-install kind-validate

PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff
ALEMBIC ?= .venv/bin/alembic
GO ?= go
ENVTEST_K8S_VERSION ?= 1.37.0
SETUP_ENVTEST_VERSION ?= v0.24.2-0.20260713111223-0f529e22d5c0
KIND ?= kind
KUBECTL ?= kubectl
KIND_CLUSTER_NAME ?= kernexys
KIND_NODE_IMAGE ?= kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
CONTROL_API_IMAGE ?= kernexys/control-api:dev
CONTROLLER_IMAGE ?= kernexys/controller:dev
MODEL_RUNTIME_V1_IMAGE ?= kernexys/model-runtime:v1
MODEL_RUNTIME_V2_IMAGE ?= kernexys/model-runtime:v2

install:
	python -m venv .venv
	$(PYTHON) -m pip install -e '.[dev]'

format:
	$(RUFF) format .
	$(RUFF) check --fix .

lint:
	$(RUFF) format --check .
	$(RUFF) check .

test:
	$(PYTHON) -m pytest --basetemp=.test-tmp/api --cov=app --cov-report=term-missing

migrate:
	$(ALEMBIC) upgrade head

run:
	$(PYTHON) -m app

container-build:
	docker compose build

container-up:
	docker compose up --build --detach --wait

container-down:
	docker compose down

# Explicitly destructive: also deletes the local PostgreSQL volume.
container-clean:
	docker compose down --volumes

controller-generate:
	cd controller && $(GO) run sigs.k8s.io/controller-tools/cmd/controller-gen@v0.21.0 object:headerFile=hack/boilerplate.go.txt paths=./api/v1alpha1
	cd controller && $(GO) run sigs.k8s.io/controller-tools/cmd/controller-gen@v0.21.0 crd paths=./api/v1alpha1 output:crd:artifacts:config=config/crd/bases
	cd controller && $(GO) run sigs.k8s.io/controller-tools/cmd/controller-gen@v0.21.0 rbac:roleName=kernexys-controller-role paths=./internal/controller output:rbac:artifacts:config=config/rbac

controller-format:
	cd controller && $(GO) fmt ./...

controller-vet:
	cd controller && $(GO) vet ./...

controller-test:
	cd controller && $(GO) test ./... -coverprofile=cover.out

controller-integration:
	cd controller && KUBEBUILDER_ASSETS="$$($(GO) run sigs.k8s.io/controller-runtime/tools/setup-envtest@$(SETUP_ENVTEST_VERSION) use --bin-dir bin/k8s --print path $(ENVTEST_K8S_VERSION))" $(GO) test ./internal/controller -run Envtest -count=1

api-kubernetes-integration:
	cd controller && KUBEBUILDER_ASSETS="$$($(GO) run sigs.k8s.io/controller-runtime/tools/setup-envtest@$(SETUP_ENVTEST_VERSION) use --bin-dir bin/k8s --print path $(ENVTEST_K8S_VERSION))" KERNEXYS_TEST_PYTHON="$(abspath $(PYTHON))" $(GO) test ./internal/controller -tags=integration -run APIKubernetes -count=1 -v

runtime-install:
	$(PYTHON) -m pip install -e './runtime[dev]'

runtime-format:
	$(RUFF) format runtime

runtime-lint:
	$(RUFF) check runtime

runtime-test:
	$(PYTHON) -m pytest runtime/tests --basetemp=.test-tmp/runtime --cov=runtime/runtime_app --cov-report=term-missing

kind-create:
	$(KIND) create cluster --name $(KIND_CLUSTER_NAME) --image $(KIND_NODE_IMAGE) --config deploy/kind/config.yaml --wait 120s

kind-delete:
	$(KIND) delete cluster --name $(KIND_CLUSTER_NAME)

kind-build:
	docker build --tag $(CONTROL_API_IMAGE) .
	docker build --file controller/Dockerfile --tag $(CONTROLLER_IMAGE) controller
	docker build --build-arg MODEL_VERSION=v1 --tag $(MODEL_RUNTIME_V1_IMAGE) runtime
	docker build --build-arg MODEL_VERSION=v2 --tag $(MODEL_RUNTIME_V2_IMAGE) runtime

kind-load:
	$(KIND) load docker-image --name $(KIND_CLUSTER_NAME) $(CONTROL_API_IMAGE) $(CONTROLLER_IMAGE) $(MODEL_RUNTIME_V1_IMAGE) $(MODEL_RUNTIME_V2_IMAGE)

kind-install:
	$(KUBECTL) apply --kustomize controller/config/default

kind-validate:
	$(KUBECTL) wait --namespace kernexys-system --for=condition=Available deployment/kernexys-controller --timeout=120s
