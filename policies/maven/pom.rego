package maven

import future.keywords.contains
import future.keywords.if
import future.keywords.in

# METADATA
# title: Maven POM Build Standards Policy
# description: Validates Maven pom.xml follows organizational build standards
# authors:
# - Prison Security Lab

# Note: Input should be pom.xml converted to JSON
# Use: yq eval -o=json pom.xml or similar

# Warn: Version must follow semantic versioning
warn contains msg if {
	version := input.project.version
	not regex.match(`^\d+\.\d+\.\d+(-SNAPSHOT)?$`, version)
	msg := sprintf("Version '%s' should follow semantic versioning (X.Y.Z or X.Y.Z-SNAPSHOT)", [version])
}

# Warn: No SNAPSHOT versions on main/master branch
warn contains msg if {
	# This will be passed as metadata from GitHub Actions
	input.metadata.branch in {"main", "master"}
	contains(input.project.version, "SNAPSHOT")
	msg := sprintf("SNAPSHOT version '%s' should not be used on production branch '%s'", [input.project.version, input.metadata.branch])
}

# Warn: Group ID should match organization
warn contains msg if {
	not startswith(input.project.groupId, "de.secureloop")
	msg := sprintf("GroupId should start with 'de.secureloop', got: %s", [input.project.groupId])
}

# Warn: Java version must be 21
warn contains msg if {
	java_version := input.project.properties["java.version"]
	not java_version == "21"
	msg := sprintf("Java version should be 21, got: %s", [java_version])
}

# Warn: Required plugins must be present
required_plugins := {"spring-boot-maven-plugin", "cyclonedx-maven-plugin"}

warn contains msg if {
	plugins := input.project.build.plugins
	existing_plugins := {plugin.artifactId | plugin := plugins[_]}
	missing := required_plugins - existing_plugins
	count(missing) > 0
	msg := sprintf("Missing required Maven plugins: %v", [missing])
}

# Warn: Spring Boot version should be recent
warn contains msg if {
	parent := input.project.parent
	parent.artifactId == "spring-boot-starter-parent"

	version_parts := split(parent.version, ".")
	count(version_parts) >= 1

	major := to_number(version_parts[0])
	major < 3

	msg := sprintf("Spring Boot version %s may be outdated, consider upgrading to 3.x or 4.x", [parent.version])
}

# Warn: License information should be present
warn contains msg if {
	not input.project.licenses
	msg := "POM should include license information for compliance"
}

warn contains msg if {
	licenses := input.project.licenses
	count(licenses) == 0
	msg := "POM should include at least one license"
}

# Warn: Project description should be present
warn contains msg if {
	not input.project.description
	msg := "POM should include project description"
}

warn contains msg if {
	description := input.project.description
	description == ""
	msg := "POM description should not be empty"
}

# Info: POM summary
summary := {
	"groupId": input.project.groupId,
	"artifactId": input.project.artifactId,
	"version": input.project.version,
	"javaVersion": object.get(input.project.properties, "java.version", "unknown"),
	"springBootVersion": object.get(input.project.parent, "version", "N/A"),
}
