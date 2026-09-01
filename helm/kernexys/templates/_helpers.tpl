{{/*
Common labels applied to every resource.
*/}}
{{- define "kernexys.labels" -}}
app.kubernetes.io/part-of: kernexys
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Resolve an image reference from a repository/tag map, honoring the optional
global registry prefix.
*/}}
{{- define "kernexys.image" -}}
{{- $registry := .global.registry -}}
{{- if $registry -}}
{{ $registry }}/{{ .image.repository }}:{{ .image.tag }}
{{- else -}}
{{ .image.repository }}:{{ .image.tag }}
{{- end -}}
{{- end -}}
