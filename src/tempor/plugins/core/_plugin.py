import glob
import importlib
import importlib.abc
import importlib.util
import os
import os.path
import sys
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Dict, List, Type, TypeVar

from typing_extensions import ParamSpec

import tempor
from tempor.log import logger

from . import utils

PLUGIN_NAME_NOT_SET = "NOT_SET"
PLUGIN_CATEGORY_NOT_SET = "NOT_SET"

P = ParamSpec("P")
T = TypeVar("T")


class Plugin:
    name: ClassVar[str] = PLUGIN_NAME_NOT_SET
    category: ClassVar[str] = PLUGIN_CATEGORY_NOT_SET

    @classmethod
    def fqn(cls) -> str:
        """The fully-qualified name of the plugin: category.name"""
        return f"{cls.category}.{cls.name}"

    def __init__(self) -> None:
        if self.name == PLUGIN_NAME_NOT_SET:
            raise ValueError(f"Plugin {self.__class__.__name__} `name` was not set, use @{register_plugin.__name__}")
        if self.category == PLUGIN_CATEGORY_NOT_SET:
            raise ValueError(
                f"Plugin {self.__class__.__name__} `category` was not set, use @{register_plugin.__name__}"
            )


PLUGIN_CATEGORY_REGISTRY: Dict[str, Type[Plugin]] = dict()
PLUGIN_REGISTRY: Dict[str, Type[Plugin]] = dict()


def register_plugin_category(category: str, expected_class: Type) -> None:
    logger.debug(f"Registering plugin category {category}")
    if category in PLUGIN_CATEGORY_REGISTRY:
        raise TypeError(f"Plugin category {category} already registered")
    if not issubclass(expected_class, Plugin):
        raise TypeError(f"Plugin expected class for category should be a subclass of {Plugin} but was {expected_class}")
    PLUGIN_CATEGORY_REGISTRY[category] = expected_class


def _check_same_class(class_1, class_2) -> bool:
    # To avoid raising "already registered" error when a certain plugin class is being reimported.
    # Not a bullet proof check but should suffice for practical purposes.
    return (
        class_1.__name__ == class_2.__name__ and class_1.__module__.split(".")[-1] == class_2.__module__.split(".")[-1]
    )


def register_plugin(name: str, category: str):
    def class_decorator(cls: Callable[P, T]) -> Callable[P, T]:
        # NOTE:
        # The Callable[<ParamSpec>, <TypeVar>] approach allows to preserve the type annotation of the parameters of the
        # wrapped class (its __init__ method, specifically). See resources:
        #     * https://stackoverflow.com/a/74080156
        #     * https://docs.python.org/3/library/typing.html#typing.ParamSpec

        if TYPE_CHECKING:  # pragma: no cover
            # Note that cls is in fact `Type[Plugin]`, but this allows to
            # silence static type-checker warnings inside this function.
            assert isinstance(cls, Plugin)  # nosec B101

        logger.debug(f"Registering plugin of class {cls}")
        cls.name = name
        cls.category = category

        if cls.category not in PLUGIN_CATEGORY_REGISTRY:
            raise TypeError(
                f"Found plugin category {cls.category} which has not been registered with "
                f"@{register_plugin_category.__name__}"
            )
        if not issubclass(cls, Plugin):
            raise TypeError(f"Expected plugin class {cls.__name__} to be a subclass of {Plugin} but was {cls}")
        if not issubclass(cls, PLUGIN_CATEGORY_REGISTRY[cls.category]):
            raise TypeError(
                f"Expected plugin class {cls.__name__} to be a subclass of "
                f"{PLUGIN_CATEGORY_REGISTRY[cls.category]} but was {cls}"
            )
        if cls.fqn() in PLUGIN_REGISTRY:
            if not _check_same_class(cls, PLUGIN_REGISTRY[cls.fqn()]):
                raise TypeError(
                    f"Plugin with fully-qualified name {cls.fqn()} already registered (as class "
                    f"{PLUGIN_REGISTRY[cls.fqn()]})"
                )
            else:
                # The same class is being reimported, do not raise error.
                pass
        for existing_cls in PLUGIN_REGISTRY.values():
            # Cannot have the same plugin name (not just fqn), as this is not supported by Pipeline.
            if cls.name == existing_cls.name:
                if not _check_same_class(cls, existing_cls):
                    raise TypeError(f"Plugin with name {cls.name} already registered (as class {existing_cls})")
                else:  # pragma: no cover
                    # The same class is being reimported, do not raise error.
                    # Some kind of coverage issues - this case *is* covered by test:
                    # test_plugins.py::TestRegistration::test_category_registration_reimport_allowed
                    pass

        PLUGIN_REGISTRY[cls.fqn()] = cls

        return cls

    return class_decorator


class PluginLoader:
    def __init__(self) -> None:
        self._refresh()

    def _refresh(self):
        self._plugin_registry: Dict[str, Type[Plugin]] = PLUGIN_REGISTRY

        name_by_category: Dict = dict()
        for plugin_class in self._plugin_registry.values():
            name_by_category = utils.append_by_dot_path(
                name_by_category, key_path=plugin_class.category, value=plugin_class.name
            )
        self._plugin_name_by_category = name_by_category

        class_by_category: Dict = dict()
        for plugin_class in self._plugin_registry.values():
            class_by_category = utils.append_by_dot_path(
                class_by_category, key_path=plugin_class.category, value=plugin_class
            )
        self._plugin_class_by_category = class_by_category

    def list(self) -> Dict:
        self._refresh()
        return self._plugin_name_by_category

    def list_fqns(self) -> List[str]:
        self._refresh()
        return list(self._plugin_registry.keys())

    def list_classes(self) -> Dict:
        self._refresh()
        return self._plugin_class_by_category

    def list_categories(self) -> Dict[str, Type[Plugin]]:
        self._refresh()
        return PLUGIN_CATEGORY_REGISTRY

    def _raise_plugin_does_not_exist_error(self, name: str):
        if name not in self._plugin_registry:
            raise ValueError(f"Plugin {name} does not exist.")

    def get(self, name: str, *args, **kwargs) -> Any:
        self._refresh()
        self._raise_plugin_does_not_exist_error(name)
        return self._plugin_registry[name](*args, **kwargs)

    def get_class(self, name: str) -> Type:
        self._refresh()
        self._raise_plugin_does_not_exist_error(name)
        return self._plugin_registry[name]


PLUGIN_FILENAME_PREFIX = "plugin_"


def _glob_plugin_paths(package_dir: str) -> List[str]:
    return [f for f in glob.glob(os.path.join(package_dir, f"{PLUGIN_FILENAME_PREFIX}*.py")) if os.path.isfile(f)]


def _module_name_from_path(path: str) -> str:
    path = os.path.normpath(path)
    split = path[path.rfind(f"{tempor.import_name}{os.sep}") :].split(os.sep)
    if split[-1][-3:] != ".py":  # pragma: no cover
        # Should be prevented by `_glob_plugin_paths`.
        raise ValueError(f"Path `{path}` is not a python file.")
    split[-1] = split[-1].replace(".py", "")
    return ".".join(split)


class importing:  # Functions as namespace, for clarity.
    @staticmethod
    def import_plugins(init_file: str) -> None:
        package_dir = os.path.dirname(init_file)
        logger.debug(f"Importing all plugin modules inside {package_dir}")
        paths = _glob_plugin_paths(package_dir=package_dir)
        logger.trace(f"Found plugin module paths to import:\n{paths}")
        for f in paths:
            module_name = _module_name_from_path(f)
            logger.debug(f"Importing plugin module: {module_name}")
            spec = importlib.util.spec_from_file_location(module_name, f)
            if spec is None or not isinstance(spec.loader, importlib.abc.Loader):
                raise RuntimeError(f"Import failed for {module_name}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

    @staticmethod
    def gather_modules_names(package_init_file: str) -> List[str]:
        package_dir = os.path.dirname(package_init_file)
        paths = _glob_plugin_paths(package_dir=package_dir)
        return [_module_name_from_path(f) for f in paths]
