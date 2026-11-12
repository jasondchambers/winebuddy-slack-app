Feature: Running the winebuddy CLI for Claude's lookups
  Claude's tool calls become winebuddy.py command lines. The command is run as a list of arguments, never
  through a shell, so nothing Claude (or a Slack user) writes can run other commands.

  Scenario Outline: Each query_wines filter becomes a winebuddy option
    When query_wines is called with <input>
    Then the winebuddy arguments are "<arguments>"

    Examples:
      | input                       | arguments                                       |
      | {"color": "Red"}            | query --format json --color Red                 |
      | {"varietal": "Pinot Noir"}  | query --format json --varietal 'Pinot Noir'     |
      | {"producer": "Vietti"}      | query --format json --producer Vietti           |
      | {"country": "Italy"}        | query --format json --country Italy             |
      | {"region": "Willamette"}    | query --format json --region Willamette         |
      | {"vintage": 2019}           | query --format json --vintage 2019              |
      | {"vintage_min": 2015}       | query --format json --vintage-min 2015          |
      | {"vintage_max": 2020}       | query --format json --vintage-max 2020          |
      | {"score_min": 92.5}         | query --format json --score-min 92.5            |
      | {"sort": "score"}           | query --format json --sort score                |
      | {"limit": 5}                | query --format json --limit 5                   |
      | {"in_stock": true}          | query --format json --in-stock                  |
      | {"ready": true}             | query --format json --ready                     |
      | {"desc": true}              | query --format json --desc                      |

  Scenario: Filters set to null and flags set to false are left out
    When query_wines is called with {"color": null, "varietal": null, "producer": null, "country": null, "region": null, "vintage": null, "vintage_min": null, "vintage_max": null, "score_min": null, "in_stock": false, "ready": false, "sort": "vintage", "desc": false, "limit": null}
    Then the winebuddy arguments are "query --format json --sort vintage"

  Scenario: A value with shell characters is passed as one argument, never through a shell
    When winebuddy is run for query_wines with {"producer": "Smith; rm -rf ~ $(whoami) `id` | cat"}
    Then the command run is "uv run --quiet python winebuddy.py query --format json --producer 'Smith; rm -rf ~ $(whoami) `id` | cat'"
    And it was run without a shell, in the winebuddy directory, with a 30 second timeout

  Scenario: winebuddy runs in its own Python environment, not the bot's
    Given the bot is running in a virtual environment
    When winebuddy is run for discover with {"field": "regions"}
    Then the command run is "uv run --quiet python winebuddy.py discover regions"
    And VIRTUAL_ENV isn't passed on to winebuddy
