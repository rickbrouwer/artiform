import argparse
import logging
import sys

import requests

from artiform import __version__
from artiform.client import ArtifactoryClient
from artiform.config import load_config
from artiform.engine import Engine
from artiform.exceptions import ArtiformError, ConfigError

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_PROCESSING_ERROR = 2


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stdout,
    )
    if not args.verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
    log = logging.getLogger("artiform")
    # First line of every run, like GitLabForm: a CI log must show which
    # version produced the result, also when the run aborts right after.
    log.info("ArtiForm version: %s", __version__)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("Config error: %s", exc)
        return EXIT_INPUT_ERROR

    client = ArtifactoryClient(
        url=config.artifactory.url,
        token=config.artifactory.token,
        verify_ssl=config.artifactory.verify_ssl,
        timeout=config.artifactory.timeout,
    )
    engine = Engine(
        config,
        client,
        dry_run=args.dry_run,
        only_projects=args.project or None,
    )
    try:
        result = engine.run()
    except ConfigError as exc:
        log.error("Config error: %s", exc)
        return EXIT_INPUT_ERROR
    except (ArtiformError, requests.RequestException) as exc:
        log.error("Fatal: %s", exc)
        return EXIT_INPUT_ERROR

    return EXIT_PROCESSING_ERROR if result.failed else EXIT_OK


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="artiform",
        description="Config-as-code for JFrog Artifactory: projects, repositories, members and cleanup policies.",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="artiform.yml",
        help="path to the config file (default: artiform.yml)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="show what would change without applying anything",
    )
    parser.add_argument(
        "-p",
        "--project",
        action="append",
        metavar="KEY",
        help="only process this project (repeatable); disables enforce_projects",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="debug logging, including HTTP requests",
    )
    parser.add_argument("--version", action="version", version=f"artiform {__version__}")
    return parser.parse_args(argv)


def run() -> None:
    sys.exit(main())
