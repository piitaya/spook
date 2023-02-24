"""Spook - Not your homey."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from hass_nabucasa import Cloud
from homeassistant.components.cloud.const import DOMAIN as CLOUD_DOMAIN
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import HomeAssistantCloudSpookEntity, SpookEntityDescription


@dataclass
class HomeAssistantCloudSpookSwitchEntityDescriptionMixin:
    """Mixin values for Home Assistant related sensors."""

    is_on_fn: Callable[[Cloud], bool | None]
    set_fn: Callable[[Cloud, bool], Awaitable[Any]]


@dataclass
class HomeAssistantCloudSpookSwitchEntityDescription(
    SpookEntityDescription,
    SwitchEntityDescription,
    HomeAssistantCloudSpookSwitchEntityDescriptionMixin,
):
    """Class describing Spook Home Assistant sensor entities."""

    icon_off: str | None = None

    def __post_init__(self) -> None:
        """Sync icon_off with icon."""
        if self.icon_off is None:
            self.icon_off = self.icon


SWITCHES: tuple[HomeAssistantCloudSpookSwitchEntityDescription, ...] = (
    HomeAssistantCloudSpookSwitchEntityDescription(
        key="alexa",
        entity_id="switch.cloud_alexa",
        name="Alexa",
        icon="mdi:account-voice",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda cloud: cloud.client.prefs.alexa_enabled,
        set_fn=lambda cloud, enabled: cloud.client.prefs.async_update(
            alexa_enabled=enabled
        ),
    ),
    HomeAssistantCloudSpookSwitchEntityDescription(
        key="google",
        entity_id="switch.cloud_google",
        name="Google Assistant",
        icon="mdi:google-assistant",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda cloud: cloud.client.prefs.google_enabled,
        set_fn=lambda cloud, enabled: cloud.client.prefs.async_update(
            google_enabled=enabled
        ),
    ),
    HomeAssistantCloudSpookSwitchEntityDescription(
        key="remote",
        entity_id="switch.cloud_remote",
        name="Remote",
        icon="mdi:remote-desktop",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda cloud: cloud.client.prefs.remote_enabled,
        set_fn=lambda cloud, enabled: cloud.client.prefs.async_update(
            remote_enabled=enabled
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Spook sensor."""
    if CLOUD_DOMAIN in hass.config.components:
        cloud: Cloud = hass.data[CLOUD_DOMAIN]
        async_add_entities(
            HomeAssistantCloudSpookSwitchEntity(cloud, description)
            for description in SWITCHES
        )


class HomeAssistantCloudSpookSwitchEntity(HomeAssistantCloudSpookEntity, SwitchEntity):
    """Spook switch providig Home Asistant Cloud controls."""

    entity_description: HomeAssistantCloudSpookSwitchEntityDescription

    async def async_added_to_hass(self) -> None:
        """Register for switch updates."""

        @callback
        def _update_state(_: Any) -> None:
            """Update state."""
            self.async_schedule_update_ha_state()

        self.async_on_remove(
            self._cloud.client.prefs.async_listen_updates(_update_state)
        )

    @property
    def icon(self) -> str | None:
        """Return the icon."""
        if self.entity_description.icon_off and self.is_on is False:
            return self.entity_description.icon_off
        return super().icon

    @property
    def is_on(self) -> bool | None:
        """Return state of the switch."""
        return self.entity_description.is_on_fn(self._cloud)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self.entity_description.set_fn(self._cloud, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self.entity_description.set_fn(self._cloud, False)
