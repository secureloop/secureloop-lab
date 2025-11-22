package sbom

import future.keywords.contains
import future.keywords.if
import future.keywords.in

# METADATA
# title: SBOM License Compliance Policy
# description: Validates CycloneDX SBOM for license compliance and completeness
# authors:
# - Prison Security Lab

# Prohibited licenses (copyleft licenses not suitable for commercial use)
prohibited_licenses := {
	"AGPL-3.0",
	"AGPL-3.0-only",
	"AGPL-3.0-or-later",
	"GPL-2.0",
	"GPL-2.0-only",
	"GPL-2.0-or-later",
	"GPL-3.0",
	"GPL-3.0-only",
	"GPL-3.0-or-later",
	"SSPL-1.0",
}

# Warn: Require valid CycloneDX format
warn contains msg if {
	not input.bomFormat == "CycloneDX"
	msg := "SBOM must be in CycloneDX format"
}

warn contains msg if {
	not input.specVersion
	msg := "SBOM must specify CycloneDX spec version"
}

# Warn: Check for prohibited licenses
warn contains msg if {
	some component in input.components
	some license in component.licenses
	license.license.id in prohibited_licenses

	msg := sprintf("Component '%s@%s' uses prohibited license: %s", [component.name, component.version, license.license.id])
}

# Warn: Missing licenses
warn contains msg if {
	some component in input.components
	not component.licenses
	msg := sprintf("Component '%s@%s' is missing license information", [component.name, component.version])
}

# Warn: Check minimum component metadata
warn contains msg if {
	some component in input.components
	not component.name
	msg := "All components must have a name"
}

warn contains msg if {
	some component in input.components
	not component.version
	msg := sprintf("Component '%s' is missing version information", [component.name])
}

# Warn: Validate SBOM completeness (should have dependencies)
warn contains msg if {
	count(input.components) < 5
	msg := sprintf("SBOM only contains %d components - may be incomplete", [count(input.components)])
}

# Warn: Check for specific vulnerable packages (log4j example)
warn contains msg if {
	some component in input.components
	contains(component.name, "log4j-core")

	# Parse version (e.g., "2.16.0" -> check if < 2.17)
	version_parts := split(component.version, ".")
	count(version_parts) >= 2

	minor := to_number(version_parts[1])
	minor < 17

	msg := sprintf("Potentially vulnerable log4j version detected: %s (should be >= 2.17)", [component.version])
}

# Info: Provide SBOM summary
summary := {
	"totalComponents": count(input.components),
	"componentsWithLicenses": count([c | c := input.components[_]; c.licenses]),
	"componentsWithoutLicenses": count([c | c := input.components[_]; not c.licenses]),
	"prohibitedLicensesFound": count([c | c := input.components[_]; some l in c.licenses; l.license.id in prohibited_licenses]),
}
