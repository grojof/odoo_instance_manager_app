## ADDED Requirements

### Requirement: UI language selection

The tool SHALL let the operator choose the interface language (Spanish or English) at startup, or via the
`OIM_LANG` environment variable, and SHALL render the interactive UI (menus, prompts, titles, table headers,
and the plan preview) in the chosen language, falling back to Spanish for any string without a translation.

#### Scenario: Language is chosen at startup

- **WHEN** the tool starts and `OIM_LANG` is not set
- **THEN** it asks the operator to choose Español or English (default Español) before showing the main menu

#### Scenario: Environment variable selects the language non-interactively

- **WHEN** `OIM_LANG` is `en` or `es`
- **THEN** the tool uses that language without prompting

#### Scenario: Menu selections are language-independent

- **WHEN** a menu is shown in English
- **THEN** each option is displayed translated but the value the tool acts on is the original, so behavior does
  not depend on the chosen language

#### Scenario: Untranslated strings fall back to Spanish

- **WHEN** a UI string has no catalog entry for the chosen language
- **THEN** the original Spanish string is shown (no error, graceful degrade)
