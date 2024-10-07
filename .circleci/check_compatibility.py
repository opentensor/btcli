#!/usr/bin/env python3

import sys
import requests
from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion, parse
import re


def main():
    if len(sys.argv) != 2:
        print("Usage: python check_compatibility.py <python_version>")
        sys.exit(1)

    python_version = sys.argv[1]
    all_passed = True

    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    NC = "\033[0m"  # No Color

    def check_compatibility():
        nonlocal all_passed
        try:
            with open("/Users/ibraheem/Desktop/btcli/btcli/requirements.txt", "r") as f:
                requirements = f.readlines()
        except FileNotFoundError:
            print(f"{RED}requirements.txt file not found.{NC}")
            sys.exit(1)

        for line in requirements:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            # Skip lines starting with git+
            if line.startswith("git+"):
                continue

            # Extract package name and version specifier
            package_name_and_specifier = re.split("[;]", line)[0].strip()
            package_name = re.split("[!=<>~]", package_name_and_specifier)[0]
            package_name = package_name.split("[")[0]  # Remove extras
            version_specifier = package_name_and_specifier[len(package_name) :].strip()

            # Request PyPi for package details
            print(f"Checking {package_name}... ", end="")
            url = f"https://pypi.org/pypi/{package_name}/json"
            response = requests.get(url)
            if response.status_code != 200:
                print(
                    f"{RED}Information not available for {package_name}. Failure.{NC}"
                )
                all_passed = False
                continue

            # Parse the data
            data = response.json()
            requires_python = data["info"]["requires_python"]

            # Parse the version specifier from requirements.txt
            requirement_specifier = (
                SpecifierSet(version_specifier) if version_specifier else None
            )

            # Get all available versions of the package
            available_versions = [parse(v) for v in data["releases"].keys()]
            available_versions.sort(reverse=True)

            # Filter versions that satisfy the requirement specifier
            if requirement_specifier:
                matching_versions = [
                    v for v in available_versions if requirement_specifier.contains(v)
                ]
            else:
                matching_versions = available_versions

            # Check for versions compatible with the specified Python version
            compatible_versions = []
            for version in matching_versions:
                releases = data["releases"].get(str(version), [])
                for release in releases:
                    # Check if the release has a 'requires_python' field
                    release_requires_python = (
                        release.get("requires_python") or requires_python
                    )
                    if release_requires_python:
                        try:
                            specifier = SpecifierSet(release_requires_python)
                            if specifier.contains(Version(python_version)):
                                compatible_versions.append(version)
                                break  # No need to check other files for this version
                        except InvalidVersion as e:
                            print(f"{RED}Invalid version in requires_python: {e}{NC}")
                            all_passed = False
                            break
                    else:
                        # If no requires_python, assume compatible
                        compatible_versions.append(version)
                        break
                if compatible_versions:
                    break  # Found the highest compatible version

            if compatible_versions:
                print(
                    f"{GREEN}Supported (compatible version: {compatible_versions[0]}){NC}"
                )
            else:
                print(f"{RED}Not compatible with Python {python_version}.{NC}")
                all_passed = False

    check_compatibility()

    if all_passed:
        print(
            f"{GREEN}All requirements are compatible with Python {python_version}.{NC}"
        )
        print(f"{GREEN}All tests passed.{NC}")
    else:
        print(
            f"{RED}Some requirements are NOT compatible with Python {python_version}.{NC}"
        )
        print(f"{RED}Some tests did not pass.{NC}")
        sys.exit(1)


if __name__ == "__main__":
    main()
