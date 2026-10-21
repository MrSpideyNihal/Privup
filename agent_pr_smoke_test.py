"""Agent PR smoke test. This file exists only to exercise the FixMySlop agent; close the PR without merging."""


def parse_rules(path):
    """Parse the rule file at path."""
    # TODO: implement this later
    pass


def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except:
        pass
