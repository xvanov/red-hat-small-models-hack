"""Form specs for the four mock platforms.

Each platform has the same fields in two layouts. "v1" is the layout the shipped mock
selector files were written against. "v2" simulates a site redesign: renamed labels,
attributes and buttons, the kind of change that breaks a scripted browser. The semantic
meaning of every field stays the same, so a model reading the page can find it again.

Field tuple: (key, kind, required, (label_v1, label_v2), options)
kind: text | number | textarea | select | checkbox | date | file | radio
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Field:
    key: str
    kind: str
    required: bool
    labels: tuple[str, str]
    options: list[str] = field(default_factory=list)

    def label(self, layout: str) -> str:
        return self.labels[0] if layout == "v1" else self.labels[1]


@dataclass
class Step:
    title: tuple[str, str]
    fields: list[Field]


@dataclass
class Platform:
    key: str
    brand: str
    tagline: str
    # how a field is hooked in the DOM: aria | id | name | testid
    hook: str
    next_label: tuple[str, str]
    submit_label: tuple[str, str]
    steps: list[Step]
    # css accent for the mock look
    accent: str = "#1877f2"


F = Field

PLATFORMS: dict[str, Platform] = {
    "marketplace": Platform(
        key="marketplace", brand="Marketplace", tagline="Create a rental listing", hook="aria",
        next_label=("Next", "Continue"), submit_label=("Publish", "Post"), accent="#1877f2",
        steps=[
            Step(("Photos", "Add photos"), [
                F("photos", "file", True, ("Add photos", "Upload photos")),
            ]),
            Step(("Rental details", "About this rental"), [
                F("home_type", "select", True, ("Home type", "Type of rental"),
                  ["Apartment", "House", "Room only", "Townhouse"]),
                F("bedrooms", "number", True, ("Number of bedrooms", "Bedrooms")),
                F("bathrooms", "number", True, ("Number of bathrooms", "Bathrooms")),
                F("price", "number", True, ("Price per month", "Monthly rent")),
                F("address", "text", True, ("Rental address", "Where is it located?")),
                F("description", "textarea", True, ("Rental description", "Describe your rental")),
            ]),
            Step(("More details", "Extra details"), [
                F("available_date", "date", True, ("Date available", "Available from")),
                F("laundry", "select", False, ("Laundry type", "Washer and dryer"),
                  ["In-unit laundry", "Laundry in building", "Laundry available", "None"]),
                F("parking", "select", False, ("Parking type", "Parking"),
                  ["Garage parking", "Street parking", "Off-street parking", "None"]),
                F("cat_friendly", "checkbox", False, ("Cat friendly", "Cats allowed")),
                F("dog_friendly", "checkbox", False, ("Dog friendly", "Dogs allowed")),
            ]),
        ],
    ),
    "roomies": Platform(
        key="roomies", brand="Roomies", tagline="List your room", hook="id",
        next_label=("Next step", "Save & continue"), submit_label=("Publish listing", "Go live"),
        accent="#00a699",
        steps=[
            Step(("The room", "Room basics"), [
                F("rent", "number", True, ("Monthly rent", "Rent per month ($)")),
                F("available_date", "date", True, ("Available from", "Move-in date")),
                F("min_stay", "select", True, ("Minimum stay", "Shortest lease"),
                  ["1 month", "3 months", "6 months", "12 months"]),
                F("private_bath", "checkbox", False, ("Private bathroom", "Bathroom is private")),
                F("furnished", "checkbox", False, ("Furnished", "Comes furnished")),
            ]),
            Step(("The place", "Your home"), [
                F("address", "text", True, ("Street or neighborhood", "Location")),
                F("headline", "text", True, ("Listing headline", "Title")),
                F("description", "textarea", True, ("Describe your place", "Tell renters about it")),
            ]),
            Step(("Photos", "Pictures"), [
                F("photos", "file", True, ("Room photos", "Add pictures")),
            ]),
        ],
    ),
    "craigslist": Platform(
        key="craigslist", brand="craigslist", tagline="create posting: housing offered", hook="name",
        next_label=("continue", "next"), submit_label=("publish", "post it"), accent="#551a8b",
        steps=[
            Step(("choose the type of posting", "what are you posting?"), [
                F("category", "radio", True, ("category", "posting category"),
                  ["apts / housing for rent", "rooms & shares", "sublets & temporary", "vacation rentals"]),
            ]),
            Step(("posting details", "describe it"), [
                F("posting_title", "text", True, ("posting title", "title")),
                F("price", "number", True, ("price", "rent")),
                F("area", "text", True, ("city or neighborhood", "location")),
                F("postal", "text", True, ("ZIP code", "postal code")),
                F("body", "textarea", True, ("description", "posting body")),
                F("available_on", "date", True, ("available on", "move-in date")),
                F("private_bath", "select", False, ("private bath", "bathroom"),
                  ["private bath", "no private bath"]),
                F("email", "text", True, ("your email address", "contact email")),
            ]),
            Step(("add images", "images"), [
                F("photos", "file", True, ("add images", "select images")),
            ]),
        ],
    ),
    "padsplit": Platform(
        key="padsplit", brand="PadSplit", tagline="Host: add a room", hook="testid",
        next_label=("Next", "Continue"), submit_label=("Submit for review", "Send to PadSplit"),
        accent="#5b2ee5",
        steps=[
            Step(("Property", "Where is the room?"), [
                F("address", "text", True, ("Property address", "Home address")),
                F("room_name", "text", True, ("Room name", "Room label")),
            ]),
            Step(("Room details", "Room setup"), [
                F("weekly_price", "number", True, ("Weekly price", "Price per week")),
                F("room_size", "select", True, ("Room size", "Size of room"), ["Small", "Medium", "Large"]),
                F("private_bath", "checkbox", False, ("Private bathroom", "Ensuite bath")),
                F("furnished", "checkbox", False, ("Furnished", "Furniture included")),
                F("available_date", "date", True, ("Available date", "Ready on")),
            ]),
            Step(("Description", "Tell members about it"), [
                F("description", "textarea", True, ("Room description", "Describe the room")),
            ]),
            Step(("Photos", "Room photos"), [
                F("photos", "file", True, ("Upload photos", "Add room photos")),
            ]),
        ],
    ),
}


def dom_name(platform: str, key: str, layout: str) -> str:
    """The form field name submitted to the mock backend. Changes between layouts."""
    if layout == "v1":
        if platform == "craigslist":
            classic = {"posting_title": "PostingTitle", "body": "PostingBody", "area": "geographic_area",
                       "email": "FromEMail", "available_on": "moveinDate", "category": "id"}
            return classic.get(key, key)
        return key
    return f"{platform[:2]}_{key}_x"


def dom_id(platform: str, key: str, layout: str) -> str:
    if layout == "v1":
        return f"{platform}-{key}".replace("_", "-")
    parts = key.split("_")
    return "f" + "".join(p.capitalize() for p in parts) + "V2"


def testid(key: str, layout: str) -> str:
    return f"{key.replace('_', '-')}-input" if layout == "v1" else f"field--{key}"
