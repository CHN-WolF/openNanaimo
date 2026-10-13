"""Install the complete four-challenge resource closure with an independent receipt."""
try:
    from . import prepare_monk_resources as resources
except ImportError:
    import prepare_monk_resources as resources


def configure():
    resources.RECIPE = resources.ROOT / 'manifest/monk_challenge_resources.json'
    resources.SCHEMA = 'openNanaimo.monk-challenges.v1'
    resources.MARKER = '.openNanaimo-monk-challenges.json'
    return resources


if __name__ == '__main__':
    configure().main()
