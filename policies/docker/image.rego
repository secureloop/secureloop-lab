package docker

import future.keywords.contains
import future.keywords.if
import future.keywords.in

# METADATA
# title: Docker Image Security Policy
# description: Validates Docker images meet security and operational standards
# authors:
# - Prison Security Lab

# Note: Input is the output of `docker inspect <image>`
# It's an array, so we access the first element

image := input[0] if count(input) > 0

# Warn: Image must run as non-root user
warn contains msg if {
	not image.Config.User
	msg := "Image must run as non-root user (set USER in Dockerfile)"
}

warn contains msg if {
	image.Config.User
	image.Config.User == "root"
	msg := "Image must not run as root user"
}

warn contains msg if {
	image.Config.User
	image.Config.User == "0"
	msg := "Image must not run as UID 0 (root)"
}

# Warn: Image tag must not be 'latest'
warn contains msg if {
	some tag in image.RepoTags
	endswith(tag, ":latest")
	msg := sprintf("Image tag should not be 'latest': %s", [tag])
}

# Warn: Image must define a healthcheck
warn contains msg if {
	not image.Config.Healthcheck
	msg := "Image must define a healthcheck for container orchestration"
}

# Warn: Required OCI labels
required_labels := {
	"org.opencontainers.image.version",
	"org.opencontainers.image.source",
	"org.opencontainers.image.revision",
}

warn contains msg if {
	not image.Config.Labels
	msg := "Image should have OCI labels defined"
}

warn contains msg if {
	image.Config.Labels
	existing_labels := {label | image.Config.Labels[label]}
	missing := required_labels - existing_labels

	count(missing) > 0
	msg := sprintf("Missing required OCI labels: %v", [missing])
}

# Warn: Base image should be from approved sources
warn contains msg if {
	some tag in image.RepoTags
	not contains(tag, "eclipse-temurin")
	not contains(tag, "openjdk")
	msg := sprintf("Base image should be eclipse-temurin or openjdk for Java applications, got: %s", [tag])
}

# Warn: Check for potential secrets in environment variables
sensitive_env_keywords := {"PASSWORD", "SECRET", "API_KEY", "TOKEN", "PRIVATE_KEY"}

warn contains msg if {
	some env in image.Config.Env
	some keyword in sensitive_env_keywords
	contains(upper(env), keyword)

	msg := sprintf("Potential secret in environment variable: %s (avoid hardcoding secrets)", [env])
}

# Warn: Exposed ports should be documented
warn contains msg if {
	not image.Config.ExposedPorts
	msg := "Image should explicitly EXPOSE ports it listens on"
}

# Info: Image summary
summary := {
	"runAsUser": image.Config.User,
	"hasHealthcheck": object.get(image.Config, "Healthcheck", null) != null,
	"exposedPorts": object.get(image.Config, "ExposedPorts", {}),
	"labels": object.get(image.Config, "Labels", {}),
}
