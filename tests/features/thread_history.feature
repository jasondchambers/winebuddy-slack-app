Feature: Reading a Slack thread back as the conversation so far
  A reply in a thread is asked along with the thread's earlier messages. The bot's messages become
  Claude's (assistant) turns and everyone else's become user turns. Messages are numbered in the order
  they were posted; "\n" in expected content is a newline.

  Scenario: People's messages are the user's and the bot's are the assistant's
    Given the thread has these messages:
      | from | text                         |
      | U1   | What Italian reds do I have? |
      | bot  | Barolo and Chianti.          |
      | U1   | Which is ready?              |
    When the history before message 3 is read
    Then the history is:
      | role      | content                      |
      | user      | What Italian reds do I have? |
      | assistant | Barolo and Chianti.          |

  Scenario: Messages from the one being answered onwards are left out
    Given the thread has these messages:
      | from | text        |
      | U1   | First       |
      | bot  | Answer      |
      | U1   | Second      |
      | U2   | Posted late |
    When the history before message 3 is read
    Then the history is:
      | role      | content |
      | user      | First   |
      | assistant | Answer  |

  Scenario: Consecutive messages from one side are joined, so the roles alternate
    Given the thread has these messages:
      | from | text              |
      | U1   | Any Barolo?       |
      | U2   | And any Chianti?  |
      | bot  | One of each.      |
      | bot  | Both ready.       |
    When the history before a new message is read
    Then the history is:
      | role      | content                             |
      | user      | Any Barolo?\n\nAnd any Chianti?     |
      | assistant | One of each.\n\nBoth ready.         |

  Scenario: The "working on it" placeholder is left out
    Given the thread has these messages:
      | from | text                          |
      | U1   | Any Barolo?                   |
      | bot  | WineBuddy is working on it... |
      | bot  | Yes, two.                     |
    When the history before a new message is read
    Then the history is:
      | role      | content     |
      | user      | Any Barolo? |
      | assistant | Yes, two.   |

  Scenario: Messages without text, such as file uploads, are left out
    Given the thread has these messages:
      | from | text        |
      | U1   | Any Barolo? |
      | U2   |             |
      | bot  | Yes, two.   |
    When the history before a new message is read
    Then the history is:
      | role      | content     |
      | user      | Any Barolo? |
      | assistant | Yes, two.   |

  Scenario: A thread the bot started begins with a note, since the history must start with the user
    Given the thread has these messages:
      | from | text                     |
      | bot  | Weekly cellar report     |
      | U1   | Which of those is ready? |
    When the history before message 2 is read
    Then the history is:
      | role      | content                                 |
      | user      | (WineBuddy posted this to the channel.) |
      | assistant | Weekly cellar report                    |

  Scenario: Only the last 20 messages are kept
    Given a thread of 30 messages taking turns between "U1" and the bot
    When the history before a new message is read
    Then the history has 20 messages, from "message 11" to "message 30"
