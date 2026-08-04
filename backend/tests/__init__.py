"""Tests du service.

`tests` est un paquet (et `consider_namespace_packages = false` dans la
configuration pytest) pour une raison précise : la roue `ultralytics` embarque
son propre paquet `tests`. Sans ces deux précautions, `from tests.support.engine
import FakeEngine` peut résoudre vers SES fichiers, et le message d'erreur ne dit
rien d'utile (piège 50 de prompt/13).
"""
