"""Spook - Not your homie."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.lovelace import DOMAIN
from homeassistant.components.lovelace.const import ConfigNotFound
from homeassistant.config_entries import SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntry
from homeassistant.const import (
    ENTITY_MATCH_ALL,
    ENTITY_MATCH_NONE,
    EVENT_COMPONENT_LOADED,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ..const import LOGGER
from . import AbstractSpookRepair

if TYPE_CHECKING:
    from homeassistant.components.lovelace.dashboard import (
        LovelaceStorage,
        LovelaceYAML,
    )
    from homeassistant.core import HomeAssistant


class SpookRepair(AbstractSpookRepair):
    """Spook repair tries to find unknown referenced entity in dashboards."""

    domain = DOMAIN
    repair = "lovelace_unknown_entity_references"
    events = {
        EVENT_COMPONENT_LOADED,
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        "event_counter_reloaded",
        "event_derivative_reloaded",
        "event_group_reloaded",
        "event_input_boolean_reloaded",
        "event_input_button_reloaded",
        "event_input_datetime_reloaded",
        "event_input_number_reloaded",
        "event_input_select_reloaded",
        "event_input_text_reloaded",
        "event_integration_reloaded",
        "event_min_max_reloaded",
        "event_mqtt_reloaded",
        "event_scene_reloaded",
        "event_schedule_reloaded",
        "event_template_reloaded",
        "event_threshold_reloaded",
        "event_tod_reloaded",
        "event_utility_meter_reloaded",
    }

    _dashboards: dict[str, LovelaceStorage | LovelaceYAML]

    async def async_activate(self) -> None:
        """Handle the activating a repair."""
        self._dashboards = self.hass.data["lovelace"]["dashboards"]
        await super().async_activate()

        # Listen for config entry changes, this might have an impact
        # on the available entities (those not in the entity registry)
        async def _async_update_listener(
            _hass: HomeAssistant,
            _entry: ConfigEntry,
        ) -> None:
            """Handle options update."""
            await self.inspect_debouncer.async_call()

        async_dispatcher_connect(
            self.hass,
            SIGNAL_CONFIG_ENTRY_CHANGED,
            _async_update_listener,
        )

    async def async_inspect(self) -> None:
        """Trigger a inspection."""
        LOGGER.debug("Spook is inspecting: %s", self.repair)

        # Two sources for entities. The entities in the entity registry,
        # and the entities currently in the state machine. They will have lots
        # of overlap, but not all entities are in the entity registry and
        # not all have to be in the state machine right now.
        # Furthermore, add `all` and `none` to the list of known entities,
        # as they are valid targets.
        entity_ids = (
            {entity.entity_id for entity in self.entity_registry.entities.values()}
            .union(self.hass.states.async_entity_ids())
            .union({ENTITY_MATCH_ALL, ENTITY_MATCH_NONE})
        )

        # Loop over all dashboards and check if there are unknown entities
        # referenced in the dashboards.
        for dashboard in self._dashboards.values():
            url_path = dashboard.url_path or "lovelace"

            try:
                config = await dashboard.async_load(force=False)
            except ConfigNotFound:
                LOGGER.debug("Config for dashboard %s not found, skipping", url_path)
                continue

            if unknown_entities := {
                entity_id
                for entity_id in self.__async_extract_entities(config)
                if (
                    isinstance(entity_id, str)
                    and not entity_id.startswith(
                        (
                            "device_tracker.",
                            "group.",
                            "persistent_notification.",
                            "scene.",
                        ),
                    )
                    and entity_id not in entity_ids
                )
            }:
                title = "Overview"
                if dashboard.config:
                    title = dashboard.config.get("title", url_path)
                self.async_create_issue(
                    issue_id=url_path,
                    translation_placeholders={
                        "entities": "\n".join(
                            f"- `{entity_id}`" for entity_id in unknown_entities
                        ),
                        "dashboard": title,
                        "edit": f"/{url_path}/0?edit=1",
                    },
                    is_fixable=True,
                )
                LOGGER.debug(
                    (
                        "Spook found unknown entities in dashboard %s "
                        "and created an issue for it; Entities: %s"
                    ),
                    title,
                    ", ".join(unknown_entities),
                )
            else:
                self.async_delete_issue(url_path)

    @callback
    def __async_extract_entities(self, config: dict[str, Any]) -> set[str]:
        """Extract entities from a dashboard config."""
        entities = set()
        for views in config.get("views", []):
            for badge in views.get("badges", []):
                entities.update(self.__async_extract_entities_from_badge(badge))
            for card in views.get("cards", []):
                entities.update(self.__async_extract_entities_from_card(card))
        return entities

    @callback
    def __async_extract_common(self, config: dict[str, Any] | str) -> set[str]:
        """Extract entities from common dashboard config."""
        entities: set[str] = set()

        if isinstance(config, str):
            return entities

        for key in ("camera_image", "entity", "entities", "entity_id"):
            if entity := config.get(key):
                if isinstance(entity, str):
                    entities.add(entity)
                if isinstance(entity, list):
                    for item in entity:
                        if isinstance(item, str):
                            entities.add(item)
                        elif (
                            isinstance(item, dict)
                            and "entity" in item
                            and isinstance(item["entity"], str)
                        ):
                            entities.add(item["entity"])
                if (
                    isinstance(entity, dict)
                    and "entity" in entity
                    and isinstance(entity["entity"], str)
                ):
                    entities.add(entity["entity"])
        return entities

    @callback
    def __async_extract_entities_from_badge(
        self,
        config: dict[str, Any] | str,
    ) -> set[str]:
        """Extract entities from a dashboard badge config."""
        if isinstance(config, str):
            return {config}
        if "entity" in config:
            return {config["entity"]}
        if "entities" in config:
            return set(config["entities"])
        return set()

    @callback
    def __async_extract_entities_from_card(self, config: dict[str, Any]) -> set[str]:
        """Extract entities from a dashboard card config."""
        entities = self.__async_extract_common(config)
        entities.update(self.__async_extract_entities_from_actions(config))

        if "condition" in config:
            entities.update(
                self.__async_extract_entities_from_condition(config["condition"]),
            )

        if "card" in config:
            entities.update(self.__async_extract_entities_from_card(config["card"]))

        for card in config.get("cards", []):
            entities.update(self.__async_extract_entities_from_card(card))

        for key in ("header", "footer"):
            if key in config:
                entities.update(
                    self.__async_extract_entities_from_header_footer(config[key]),
                )

        for element in config.get("elements", []):
            entities.update(self.__async_extract_entities_from_element(element))

        # Mushroom
        if "chips" in config:
            for chip in config["chips"]:
                entities.update(self.__async_extract_entities_from_mushroom_chip(chip))

        return entities

    @callback
    def __async_extract_entities_from_actions(self, config: dict[str, Any]) -> set[str]:
        """Extract entities from a dashboard config containing actions."""
        entities = set()
        for key in (
            "tap_action",
            "hold_action",
            "double_tap_action",
            "subtitle_tap_action",
        ):
            if key in config:
                entities.update(self.__async_extract_entities_from_action(config[key]))
        return entities

    @callback
    def __async_extract_entities_from_action(self, config: dict[str, Any]) -> set[str]:
        """Extract entities from a dashboard action config."""
        entities = set()
        for key in ("service_data", "target"):
            if key in config and (entity_id := config[key].get("entity_id")):
                if isinstance(entity_id, str):
                    entities.add(entity_id)
                else:
                    entities.update(entity_id)
        return entities

    @callback
    def __async_extract_entities_from_condition(
        self,
        config: dict[str, Any],
    ) -> set[str]:
        """Extract entities from a dashboard element config."""
        if "entity" in config and isinstance(config["entity"], str):
            return {config["entity"]}
        return set()

    @callback
    def __async_extract_entities_from_element(self, config: dict[str, Any]) -> set[str]:
        """Extract entities from a dashboard element config."""
        entities = self.__async_extract_common(config)
        entities.update(self.__async_extract_entities_from_actions(config))
        entities.update(self.__async_extract_entities_from_action(config))

        if "conditions" in config:
            for condition in config["conditions"]:
                entities.update(self.__async_extract_entities_from_condition(condition))

        if "elements" in config:
            for element in config["elements"]:
                entities.update(self.__async_extract_entities_from_element(element))

        return entities

    @callback
    def __async_extract_entities_from_header_footer(
        self,
        config: dict[str, Any],
    ) -> set[str]:
        """Extract entities from a dashboard haeder footer config."""
        entities = self.__async_extract_common(config)
        entities.update(self.__async_extract_entities_from_actions(config))
        return entities

    @callback
    def __async_extract_entities_from_mushroom_chip(
        self,
        config: dict[str, Any],
    ) -> set[str]:
        """Extract entities from mushroom chips."""
        entities = self.__async_extract_common(config)
        if "chip" in config:
            entities.update(
                self.__async_extract_entities_from_mushroom_chip(config["chip"]),
            )
        if "conditions" in config:
            for condition in config["conditions"]:
                entities.update(self.__async_extract_entities_from_condition(condition))
        return entities
