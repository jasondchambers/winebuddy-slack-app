Feature: Answering a question with Claude and the winebuddy CLI
  ask() refreshes the cellar, then asks Claude, running the query_wines and discover lookups Claude asks
  for until it answers. Claude and the winebuddy CLI are faked: Claude's turns are scripted in order, and
  winebuddy's output is given per command line.

  Background:
    Given the skill file says "Look up wines with winebuddy."
    And the cellar refresh reports "Database is up to date"

  Scenario: Claude answers without looking anything up
    Given Claude replies "You have 12 bottles."
    When I ask "How many bottles do I have?"
    Then the answer is "You have 12 bottles."
    And Claude was sent "How many bottles do I have?" after the refresh output "Database is up to date"

  Scenario: The system prompt is the skill without its front matter, the bot instructions and today's date
    Given Claude replies "Hello."
    When I ask "Hi"
    Then the system prompt starts with "Look up wines with winebuddy."
    And the system prompt includes "## Running as the Slack bot"
    And the system prompt ends with today's date

  Scenario: A lookup is run and its result sent back to Claude
    Given Claude calls query_wines with {"country": "Italy", "in_stock": true}
    And winebuddy outputs '[{"wine": "Barolo"}]' for "query --format json --country Italy --in-stock"
    And Claude replies "You have a Barolo."
    When I ask "Any Italian wine?"
    Then winebuddy was run with "query --format json --country Italy --in-stock"
    And Claude was sent the tool result '[{"wine": "Barolo"}]'
    And the answer is "You have a Barolo."

  Scenario: Several lookups in one turn are all run and sent back together
    Given Claude calls discover for "regions" and query_wines with {"color": "Red"}
    And Claude replies "Done."
    When I ask "What regions and reds?"
    Then winebuddy was run with "discover regions"
    And winebuddy was run with "query --format json --color Red"
    And Claude was sent 2 tool results

  Scenario: The answer is passed on as it streams in
    Given Claude replies in pieces "You have", " 12", " bottles."
    When I ask "How many bottles?"
    Then the answer so far was passed on as:
      | text                 |
      | You have             |
      | You have 12          |
      | You have 12 bottles. |
    And the answer is "You have 12 bottles."

  Scenario: Earlier messages in the thread come before the question
    Given Claude replies "The Barolo."
    When I ask "Which is ready?" after this conversation:
      | role      | content                      |
      | user      | What Italian reds do I have? |
      | assistant | Barolo and Chianti.          |
    Then Claude was sent these messages before the question:
      | role      | content                      |
      | user      | What Italian reds do I have? |
      | assistant | Barolo and Chianti.          |

  Scenario: A failed lookup goes back to Claude as an error
    Given Claude calls discover for "regions"
    And winebuddy fails with "no such table: wines" for "discover regions"
    And Claude replies "Sorry, the cellar looks empty."
    When I ask "What regions?"
    Then Claude was sent the error "error: no such table: wines"
    And the answer is "Sorry, the cellar looks empty."

  Scenario: A lookup that times out goes back to Claude as an error
    Given Claude calls discover for "regions"
    And winebuddy times out for "discover regions"
    And Claude replies "Sorry, that took too long."
    When I ask "What regions?"
    Then Claude was sent the error "error: the lookup timed out"

  Scenario: A lookup with no output says so
    Given Claude calls discover for "regions"
    And winebuddy outputs '' for "discover regions"
    And Claude replies "No regions."
    When I ask "What regions?"
    Then Claude was sent the tool result '(no output)'

  Scenario: Lookups stop after 10 rounds
    Given Claude keeps calling discover for "regions"
    When I ask "What regions?"
    Then the answer is "_Stopped: that question needed too many lookups._"
    And Claude was called 10 times

  Scenario: A refusal gets a short apology
    Given Claude refuses
    When I ask "Something off-topic"
    Then the answer is "Sorry, I can't help with that one."

  Scenario: An answer cut off at the token limit is returned as it is, without running its lookups
    Given Claude writes "Let me check" and calls discover for "regions" but hits the token limit
    When I ask "What regions?"
    Then the answer is "Let me check"
    And winebuddy was only run to refresh the cellar

  Scenario: Text Claude wrote before a lookup is kept when its last turn adds none
    Given Claude writes "Here are your regions." and calls discover for "regions"
    And Claude replies ""
    When I ask "What regions?"
    Then the answer is "Here are your regions."

  Scenario: An empty answer says so
    Given Claude replies ""
    When I ask "Hi"
    Then the answer is "No response from Claude"

  Scenario Outline: A refresh that finds the cellar up to date, new or changed is passed to Claude
    Given the cellar refresh exits with <code> reporting "<report>"
    And Claude replies "OK."
    When I ask "Anything new?"
    Then Claude was sent "Anything new?" after the refresh output "<report>"

    Examples:
      | code | report                   |
      | 0    | Database is up to date   |
      | 1    | Created database         |
      | 2    | Rebuilt: 3 new wines     |

  Scenario: A missing cellar.csv means the question can't be answered
    Given the cellar refresh exits with 255 reporting ""
    When I ask "Any Barolo?"
    Then asking fails with "the cellar couldn't be refreshed (cellar.csv is missing)"
    And Claude was called 0 times

  Scenario: Any other refresh failure gives winebuddy's error
    Given the cellar refresh fails with exit 3 and "database is locked"
    When I ask "Any Barolo?"
    Then asking fails with "the cellar couldn't be refreshed (database is locked)"
    And Claude was called 0 times
