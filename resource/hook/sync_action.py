# :coding: utf-8
# :copyright: Copyright (c) 2018 ftrack

from typing import List, Dict, Any, Optional, Union
import os
import sys
import logging

dependencies_directory: str = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "dependencies")
)

sys.path.append(dependencies_directory)


import ftrack_api
import ftrack_api.session
import ftrack_api.entity.base
from ftrack_action_handler.action import BaseAction
from ftrack_user_location import sync

logger: logging.Logger = logging.getLogger("ftrack_user_location.SyncAction")


class SyncAction(BaseAction):

    name: str = "ftrack sync tool"
    label: str = "ftrack sync tool"
    identifier: str = "ftrack.fsync"

    def __init__(self, session: "ftrack_api.session.Session") -> None:
        super(SyncAction, self).__init__(session)
        self._location_data: Dict[str, Any] = {}
        self._sync_data: Dict[str, Any] = {}
        # Locations to exclude from sync dropdown
        # Include ftrack.server as it's the primary sync target
        # Exclude only internal/system locations
        self._ignored_locations: List[str] = [
            "ftrack.origin",  # Original file location (not a sync target)
            "ftrack.unmanaged",  # Unmanaged files
            "ftrack.connect",  # Connect internal location
            "ftrack.review",  # Review proxy location
        ]

        # Cache current user ID (lazy-loaded on first access)
        self._current_user_id: Optional[str] = None

    @property
    def current_user_id(self) -> str:
        """Lazy-load current user ID on first access to avoid querying during plugin discovery."""
        if self._current_user_id is None:
            self._current_user_id = self.session.query(
                'User where username is "{}"'.format(self.session.api_user)
            ).first()["id"]
        return self._current_user_id

    @property
    def variant(self) -> str:
        return "Sync @ {}".format(self.location["name"])

    @property
    def location(self) -> "ftrack_api.entity.base.Entity":
        return self.session.pick_location()

    def get_locations(
        self, name: bool = False
    ) -> Union[List["ftrack_api.entity.base.Entity"], List[str]]:
        locations = self.session.query("select name from Location").all()
        if name:
            locations = [x["name"] for x in locations]
        return locations

    def get_current_location(
        self, name: bool = False
    ) -> Union["ftrack_api.entity.base.Entity", str]:
        location = self.location
        if name:
            location = location["name"]
        return location

    def get_locations_menu(
        self,
        field_id: str,
        label: Optional[str] = None,
        default_value: Optional[List[str]] = None,
        exclude_self: bool = False,
        exclude_inaccessibles: bool = False,
    ) -> Dict[str, Any]:
        """Build location dropdown menu for sync action.

        Shows:
        - User locations (e.g., username.hostname)
        - ftrack.server (primary sync target)

        Excludes:
        - Internal ftrack locations (origin, unmanaged, connect, review)
        - Self location if exclude_self=True
        - Inaccessible locations if exclude_inaccessibles=True
        """
        location_menu: Dict[str, Any] = {
            "label": label,
            "type": "enumerator",
            "name": field_id,
            "value": default_value or [],
            "data": [],
        }

        locations: List["ftrack_api.entity.base.Entity"] = self.get_locations()

        if exclude_self:
            locations = [x for x in locations if not x["name"] == self.location["name"]]

        # Filter out internal ftrack locations (but keep ftrack.server for sync)
        locations = [x for x in locations if x["name"] not in self._ignored_locations]

        if exclude_inaccessibles:
            # Filter non-accessible locations
            locations = [x for x in locations if x.accessor]

        locations = sorted(locations, key=lambda x: x["name"], reverse=True)

        for location in locations:

            item = {"label": location["name"], "value": location["name"]}

            location_menu["data"].append(item)

        return location_menu

    def location_exists(self, location: str) -> bool:
        return location in self.get_locations(name=True)

    def build_sync_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Build sync event with comprehensive validation.

        Args:
            event: Action event with form values

        Returns:
            Modified event with sync parameters

        Raises:
            ValueError: If validation fails
        """
        values: Dict[str, Any] = event["data"].get("values", {})

        source_location = values.get("source_location")
        dest_location = values.get("dest_location")

        # Validate required fields
        if not source_location:
            raise ValueError("Source location is required")
        if not dest_location:
            raise ValueError("Destination location is required")

        # Prevent self-sync
        if source_location == dest_location:
            raise ValueError("Source and destination must be different")

        # Validate locations exist
        if not self.location_exists(source_location):
            raise ValueError(
                'Source location "{}" does not exist'.format(source_location)
            )

        if not self.location_exists(dest_location):
            raise ValueError(
                'Destination location "{}" does not exist'.format(dest_location)
            )

        # Validate locations are accessible (have accessors)
        source_loc = self.session.get("Location", source_location)
        dest_loc = self.session.get("Location", dest_location)

        if not source_loc.accessor:
            raise ValueError(
                'Source location "{}" is not accessible from this machine. '
                "You can only sync from locations that are registered on your local machine.".format(
                    source_loc["name"]
                )
            )

        if not dest_loc.accessor:
            raise ValueError(
                'Destination location "{}" is not accessible from this machine.'.format(
                    dest_loc["name"]
                )
            )

        # Build event
        event["data"]["actionIdentifier"] = "syncto-{}".format(dest_location)
        event["source"]["location"] = self.location["name"]
        event["target"] = {"location": dest_location}

        return event

    def get_locations_ui(self, event: Dict[str, Any]) -> Dict[str, Any]:
        menu: Dict[str, Any] = {
            "type": "form",
            "items": [],
            "title": "Sync Tool",
            "submit_button_label": "Sync",
        }

        menu["items"].append(
            {"value": "## {} ##".format(self.location["name"]), "type": "label"}
        )

        menu["items"].append({"value": "Locations", "type": "label"})

        menu["items"].append(
            self.get_locations_menu(
                "source_location",
                label="Source",
                default_value=self.get_current_location(name=True),
                # exclude_inaccessibles=True
            )
        )

        menu["items"].append(
            self.get_locations_menu(
                "dest_location",
                label="Destination",
                # exclude_self=True
            )
        )

        event.update(menu)
        return event

    def sync_here(
        self, event: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:

        try:
            sync.on_sync_to_destination(
                self.session,
                event["data"]["locations"]["sync"],
                event["data"]["locations"]["destination"],
                event["data"]["components"],
                event["source"]["user"]["id"],
            )
        except Exception:
            import traceback

            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": ("Something failed," " please check the logs"),
            }
            raise

    def sync_there(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            _id: str = event["source"]["id"]
            source_location = event["data"]["values"]["source_location"]
            dest_location = event["data"]["values"]["dest_location"]

            sync.on_sync_to_remote(
                self.session,
                source_location,
                dest_location,
                event["source"]["user"]["id"],
                event["data"].get("selection", []),
            )
            self._location_data.pop(_id) if _id in self._location_data else None

        except Exception:
            import traceback

            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": ("Something failed," " please check the logs"),
            }
            raise

    def discover(
        self,
        session: "ftrack_api.session.Session",
        entities: List[tuple],
        event: Dict[str, Any],
    ) -> bool:
        """Discover action only for current user to prevent duplicates.

        When multiple users run ftrack Connect, each registers their own
        action handler. We filter by matching the event source user with
        the current session user to ensure only one action appears per user.
        """
        if not entities:
            return False

        entity_type: str
        entity_id: str
        entity_type, entity_id = entities[0]
        if entity_type != "AssetVersion":
            return False

        # Only respond to discovery from the same user that registered this action
        # This prevents multiple action instances appearing when multiple users
        # are running ftrack Connect simultaneously
        event_user_id: Optional[str] = event.get("source", {}).get("user", {}).get("id")

        if event_user_id and event_user_id != self.current_user_id:
            # This discovery event is from a different user's Connect instance
            # Don't respond to prevent duplicate actions in UI
            return False

        return True

    def _discover(self, event: Dict[str, Any]) -> Dict[str, Any]:
        accepts: Dict[str, Any] = super(SyncAction, self)._discover(event)
        # add location to discovered item.

        if accepts:
            for item in accepts["items"]:
                item["location"] = self.location["name"]

        return accepts

    def launch(
        self,
        session: "ftrack_api.session.Session",
        entities: List[tuple],
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Launch sync action with comprehensive error handling.

        Args:
            session: ftrack API session
            entities: Selected entities
            event: Action event

        Returns:
            Success/failure message or form UI
        """
        self.logger.info(
            "Sync action launched from location {}".format(self.location["name"])
        )

        if "values" not in event["data"]:
            # Show form
            event = self.get_locations_ui(event)
            return event
        else:
            try:
                event = self.build_sync_event(event)
            except ValueError as e:
                self.logger.warning("Validation error: {}".format(e))
                return {"success": False, "message": str(e)}
            except Exception as e:
                self.logger.error("Unexpected error building sync event: {}".format(e))
                import traceback

                self.logger.error(traceback.format_exc())
                return {
                    "success": False,
                    "message": "An unexpected error occurred. Please check logs.",
                }

            # Publish event
            try:
                event["data"]["actionIdentifier"] = "{}-to-ftrack".format(
                    self.location["name"]
                )
                self.session.event_hub.publish(event)

                return {"success": True, "message": "Sync launched successfully"}
            except Exception as e:
                self.logger.error("Failed to publish sync event: {}".format(e))
                import traceback

                self.logger.error(traceback.format_exc())
                return {
                    "success": False,
                    "message": "Failed to launch sync. Please try again.",
                }

    def register(self) -> None:
        # ensure session has been finishing to load and discovered locations.
        self.session.event_hub.subscribe(
            "topic=ftrack.api.session.ready", self._register
        )

    def _register(self, event: Dict[str, Any]) -> None:
        # discover action
        self.session.event_hub.subscribe("topic=ftrack.action.discover", self._discover)

        # launch action
        self.session.event_hub.subscribe(
            "topic=ftrack.action.launch and data.actionIdentifier={0}"
            ' and data.location="{1}"'.format(self.identifier, self.location["name"]),
            self._launch,
        )

        # register event for every accessible location
        for location in self.get_locations():
            if location.accessor:
                # listen to transfer events.
                self.session.event_hub.subscribe(
                    "data.actionIdentifier={0}-to-ftrack".format(location["name"]),
                    self.sync_there,
                )

                self.session.event_hub.subscribe(
                    "topic=ftrack.sync and data.actionIdentifier=ftrack-to-{0}".format(
                        location["name"]
                    ),
                    self.sync_here,
                )


def register(api_object: Any, **kwargs: Any) -> None:
    # Validate that session is an instance of ftrack_api.Session. If not,
    # assume that register is being called from an incompatible API
    # and return without doing anything.
    if not isinstance(api_object, ftrack_api.Session):
        return

    action: SyncAction = SyncAction(api_object)
    logger.info("Registering : {}".format(api_object))
    action.register()
