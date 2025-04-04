import json

from . import cps

from typing import Dict


def load(file) -> cps.Package:
    with open(file, "r") as f:
        return loads(f.read())


def loads(load: str) -> cps.Package:
    return loadd(json.loads(load))


def loadd(load: Dict) -> cps.Package:
    return cps.Package.from_dict(load)


def dumpd(cps: cps.Package) -> dict:
    cps.to_dict()


def dumps(cps: cps.Package) -> str:
    return json.dumps(dumpd(cps))


def dump(cps: cps.Package, file) -> None:
    with open(file, "w+") as f:
        f.write(dumps(cps))
