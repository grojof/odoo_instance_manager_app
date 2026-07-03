# ui-localization Specification

## Purpose
TBD - created by archiving change add-ui-localization. Update Purpose after archive.
## Requirements
### Requirement: UI language selection

The tool SHALL treat English as the canonical source language (English string literals in the code) and SHALL let the operator choose the interface language (English or Spanish) at startup, or via the `OIM_LANG` environment variable, defaulting to English, and SHALL render every user-facing surface (menus, prompts, titles, table headers and string row cells, command/plan descriptions, interpolated status messages, and one-off prints) in the chosen language, falling back to the English source for any string without a Spanish translation.

#### Scenario: Language is chosen at startup

- **WHEN** the tool starts and `OIM_LANG` is not set
- **THEN** it asks the operator to choose Español or English before showing the main menu

#### Scenario: Environment variable selects the language non-interactively

- **WHEN** `OIM_LANG` is `en` or `es`
- **THEN** the tool uses that language without prompting

#### Scenario: English is the default and the identity

- **WHEN** English is selected (including by default)
- **THEN** every string is shown as written in the code, with no catalog lookup required

#### Scenario: Spanish is a complete translation

- **WHEN** Spanish is selected
- **THEN** menus, prompts, titles, table headers and string cells, command/plan descriptions, and interpolated status messages are all shown in Spanish

#### Scenario: Menu selections are language-independent

- **WHEN** a menu is shown in Spanish
- **THEN** each option is displayed translated but the value the tool acts on is the original English option, so behavior does not depend on the chosen language

#### Scenario: Untranslated strings fall back to English

- **WHEN** a UI string has no Spanish catalog entry
- **THEN** the original English string is shown (no error, graceful degrade)

