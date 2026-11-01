{{- define "sso.issuer" -}}
https://{{ .root.Values.idp.host }}/realms/{{ .realm }}
{{- end }}

{{/* Keycloak at its public URL = the gateway's own HTTPS listener: the envoy-edge Service (EDS, no DNS).
The edge chart grants the reference (ReferenceGrant) and adds the BackendTLSPolicy with the mkcert CA. */}}
{{- define "sso.backendRefs" -}}
- group: ""
  kind: Service
  name: {{ .root.Values.idp.gatewayService.name }}
  namespace: {{ .root.Values.idp.gatewayService.namespace }}
  port: {{ .root.Values.idp.gatewayService.port }}
{{- end }}

{{/* Envoy's calls to Keycloak (code exchange, refresh, JWKS) are retried on transient failures, as
in the Envoy Gateway OIDC task. */}}
{{- define "sso.backendSettings" -}}
retry:
  numRetries: 3
  perRetry:
    backOff:
      baseInterval: 200ms
      maxInterval: 2s
  retryOn:
    triggers: ["5xx", "gateway-error", "reset", "connect-failure"]
{{- end }}

{{- define "sso.targetRefs" -}}
{{- range . }}
- group: gateway.networking.k8s.io
  kind: HTTPRoute
  name: {{ . }}
{{- end }}
{{- end }}

{{/* JWT provider for a realm: issuer, audiences, JWKS fetched through the Backend. */}}
{{- define "sso.jwtProvider" -}}
- name: keycloak-{{ .realm }}
  issuer: {{ include "sso.issuer" . }}
  {{- with .audiences }}
  audiences:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  remoteJWKS:
    uri: {{ include "sso.issuer" . }}/protocol/openid-connect/certs
    backendRefs:
      {{- include "sso.backendRefs" . | nindent 6 }}
    backendSettings:
      {{- include "sso.backendSettings" . | nindent 6 }}
{{- end }}
