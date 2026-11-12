Feature: Answering Slack messages
  The bot replies to each message in that message's thread: it posts a "working on it" placeholder, then
  updates the placeholder with the answer. Asking Claude is faked, and so is the clock.
  Quoted text can use backslash escapes such as \n and \x00.

  Scenario: A message is answered in its thread
    Given Claude answers "You have 3 Barolos."
    When "U1" posts "How many Barolos do I have?"
    Then the bot posts "WineBuddy is working on it..." in the thread
    And the reply is updated to "You have 3 Barolos."
    And Claude was asked "How many Barolos do I have?" with no earlier messages

  Scenario: Markdown bold in the answer is turned into Slack bold
    Given Claude answers "You have **3** Barolos and **2** Chiantis."
    When "U1" posts "How many Italian reds?"
    Then the reply is updated to "You have *3* Barolos and *2* Chiantis."

  Scenario: A reply in a thread is asked along with the thread so far
    Given a thread where "U1" asked "What Italian reds do I have?" and the bot answered "Barolo and Chianti."
    And Claude answers "The Barolo is ready now."
    When "U1" replies in the thread "Which is ready to drink?"
    Then the bot posts "WineBuddy is working on it..." in the thread
    And Claude was asked "Which is ready to drink?" with these earlier messages:
      | role      | content                      |
      | user      | What Italian reds do I have? |
      | assistant | Barolo and Chianti.          |

  Scenario: Messages from bots are ignored
    When a bot posts "Hello from another bot"
    Then the bot posts nothing
    And Claude was not asked

  Scenario: A second message within 5 seconds is refused
    Given Claude answers "Yes."
    When "U1" posts "First question"
    And "U1" posts "Second question" 3 seconds later
    Then the last thing the bot posts is "Please wait 5 seconds between requests."
    And Claude was asked 1 time

  Scenario: A message 5 seconds after the last one is answered
    Given Claude answers "Yes."
    When "U1" posts "First question"
    And "U1" posts "Second question" 5 seconds later
    Then Claude was asked 2 times

  Scenario: People aren't rate limited by each other's messages
    Given Claude answers "Yes."
    When "U1" posts "First question"
    And "U2" posts "Another question" 1 seconds later
    Then Claude was asked 2 times

  Scenario: A message with only spaces is refused
    When "U1" posts "   "
    Then the bot posts "Sorry, your message was empty or too long (max 2000 characters)." in the thread
    And Claude was not asked

  Scenario: A message over 2000 characters is refused
    When "U1" posts a message of 2001 characters
    Then the bot posts "Sorry, your message was empty or too long (max 2000 characters)." in the thread
    And Claude was not asked

  Scenario: A message of exactly 2000 characters is answered
    Given Claude answers "That's a long one."
    When "U1" posts a message of 2000 characters
    Then Claude was asked 1 time

  Scenario: Control characters are removed, but newlines and tabs are kept
    Given Claude answers "Yes."
    When "U1" posts "\x00Any\x07 Barolo?\x1b\nAnd\tChianti?\x7f"
    Then Claude was asked "Any Barolo?\nAnd\tChianti?" with no earlier messages

  Scenario: The answer is shown as it streams in, at most every 2 seconds
    Given Claude's answer streams in as:
      | seconds | answer so far                       |
      | 1       | Barolo                              |
      | 2.5     | Barolo and Chianti                  |
      | 3       | Barolo and Chianti, both            |
      | 5       | Barolo and Chianti, both ready now. |
    When "U1" posts "What's ready?"
    Then the reply is updated in turn to:
      | text                                |
      | Barolo and Chianti                  |
      | Barolo and Chianti, both ready now. |
      | Barolo and Chianti, both ready now. |

  Scenario: When the cellar can't be refreshed, the reply says why
    Given the cellar can't be refreshed because cellar.csv is missing
    When "U1" posts "Any Barolo?"
    Then the reply is updated to "Sorry, the cellar couldn't be refreshed (cellar.csv is missing)."

  Scenario: When Claude can't be reached, the reply asks to try again
    Given the Claude API can't be reached
    When "U1" posts "Any Barolo?"
    Then the reply is updated to "Sorry, I couldn't reach Claude. Please try again in a minute."
