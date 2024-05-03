#!/usr/bin/env python
"""ffreplex entry point"""

import logging
import argparse


def get_options():
    description = ''
    parser = argparse.ArgumentParser(description=description)

    # parser.add_argument('name',
    #                     help='Name')

    return parser.parse_args()


def set_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    logger.addHandler(ch)
    return logger


if __name__ == "__main__":
    options = get_options()
    logger = set_logging()
    logger.info('Salut')
