{{- define "incident-triage-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "incident-triage-mcp.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "incident-triage-mcp.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "incident-triage-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "incident-triage-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "incident-triage-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "incident-triage-mcp.agentJobSecretName" -}}
{{ include "incident-triage-mcp.fullname" . }}-agent-job-env
{{- end -}}

{{- define "incident-triage-mcp.agentJobMcpUrl" -}}
{{- $svcPort := .Values.service.port | toString -}}
{{- printf "http://%s.%s.svc.cluster.local:%s/mcp" (include "incident-triage-mcp.fullname" .) .Release.Namespace $svcPort -}}
{{- end -}}
