# IF things in this file continue get messy (I'd say 300+ lines) it may be time to
# find a package that parses https://schema.org/Recipe properly (or create one ourselves).

from operator import is_not
from typing import Any, Dict, List, Optional

import extruct

from ._utils import get_minutes, normalize_string

SCHEMA_ORG_HOST = "schema.org"
SCHEMA_NAMES = ["Recipe", "WebPage"]

SYNTAXES = ["json-ld", "microdata"]


class SchemaOrgException(Exception):
    def __init__(self, message):
        super().__init__(message)


class SchemaOrg:
    def __init__(self, page_data):
        self.format = None
        self.data = {}

        data = extruct.extract(page_data, syntaxes=SYNTAXES, uniform=True)

        low_schema = {s.lower() for s in SCHEMA_NAMES}
        for syntax in SYNTAXES:
            for item in data.get(syntax, []):
                in_context = SCHEMA_ORG_HOST in item.get("@context", "")
                if in_context and item.get("@type", "").lower() in low_schema:
                    self.format = syntax
                    self.data = item
                    if item.get("@type").lower() == "webpage":
                        self.data = self.data.get("mainEntity")
                    return
                elif in_context and "@graph" in item:
                    for graph_item in item.get("@graph", ""):
                        graph_item_type = graph_item.get("@type", "")
                        if not isinstance(graph_item_type, str):
                            continue
                        if graph_item_type.lower() in low_schema:
                            in_graph = SCHEMA_ORG_HOST in graph_item.get("@context", "")
                            self.format = syntax
                            if graph_item_type.lower() == "webpage" and in_graph:
                                self.data = self.data.get("mainEntity")
                                return
                            elif graph_item_type.lower() == "recipe":
                                self.data = graph_item
                                return

    def language(self) -> Optional[str]:
        return self.data.get("inLanguage") or self.data.get("language")

    def title(self) -> Optional[str]:
        return normalize_string(self.data.get("name"))

    def author(self) -> Optional[str]:
        author = self.data.get("author")
        if (
            author
            and isinstance(author, list)
            and len(author) >= 1
            and isinstance(author[0], dict)
        ):
            author = author[0]
        if author and isinstance(author, dict):
            author = author.get("name")
        return author

    def total_time(self) -> Optional[int]:
        def get_key_and_minutes(k):
            return get_minutes(self.data.get(k))

        def not_none(x) -> bool:
            return is_not(x, None)

        total_time = get_key_and_minutes("totalTime")
        if total_time is None:
            times: List[int] = list(
                filter(not_none, map(get_key_and_minutes, ["prepTime", "cookTime"]))
            )
            total_time = sum(times) if times else None
        return total_time

    def yields(self) -> Optional[str]:
        yield_data = self.data.get("recipeYield")
        if yield_data:
            if isinstance(yield_data, list):
                yield_data = yield_data[0]
            recipe_yield = str(yield_data)

        if yield_data is None:
            raise SchemaOrgException("Yields not found in SchemaOrg")

        if len(recipe_yield) <= 3:  # probably just a number. append "servings"
            return recipe_yield + " serving(s)"

        if "\n" in recipe_yield:
            recipe_yield = recipe_yield.rsplit("\n", 1)[-1]

        return recipe_yield

    def image(self) -> Optional[str]:
        image = self.data.get("image")

        if image is None:
            raise SchemaOrgException("Image not found in SchemaOrg")

        if isinstance(image, list):
            # Could contain a dict
            image = image[0]

        if isinstance(image, dict):
            image = image.get("url")

        if "http://" not in image and "https://" not in image:
            # some sites give image path relative to the domain
            # in cases like this handle image url with class methods or og link
            image = ""

        return image

    def ingredients(self) -> Optional[List[str]]:
        ingredients = (
            self.data.get("recipeIngredient") or self.data.get("ingredients") or []
        )
        return [
            normalize_string(ingredient) for ingredient in ingredients if ingredient
        ]

    def nutrients(self) -> Optional[Dict[str, Any]]:
        nutrients = self.data.get("nutrition", {})
        return {
            normalize_string(nutrient): normalize_string(value)
            for nutrient, value in nutrients.items()
            if nutrient != "@type"
        }

    def _extract_howto_instructions_text(self, schema_item):
        instructions_gist = []
        if type(schema_item) is str:
            instructions_gist.append(schema_item)
        elif schema_item.get("@type") == "HowToStep":
            if schema_item.get("name", False):
                # some sites have duplicated name and text properties (1:1)
                # others have name same as text but truncated to X chars.
                # ignore name in these cases and add the name value only if it's different from the text
                if not schema_item.get("text").startswith(
                    schema_item.get("name").rstrip(".")
                ):
                    instructions_gist.append(schema_item.get("name"))
            instructions_gist.append(schema_item.get("text"))
        elif schema_item.get("@type") == "HowToSection":
            instructions_gist.append(schema_item.get("name") or schema_item.get("Name"))
            for item in schema_item.get("itemListElement"):
                instructions_gist += self._extract_howto_instructions_text(item)
        return instructions_gist

    def instructions(self) -> Optional[str]:
        instructions = self.data.get("recipeInstructions") or ""

        if isinstance(instructions, list):
            instructions_gist = []
            for schema_instruction_item in instructions:
                instructions_gist += self._extract_howto_instructions_text(
                    schema_instruction_item
                )

            return "\n".join(
                normalize_string(instruction) for instruction in instructions_gist
            )

        return instructions

    def ratings(self) -> Optional[float]:
        ratings = self.data.get("aggregateRating")
        if ratings is None:
            raise SchemaOrgException("No ratings data in SchemaOrg.")

        if isinstance(ratings, dict):
            ratings = ratings.get("ratingValue")

        if ratings is None:
            raise SchemaOrgException("No ratingValue in SchemaOrg.")

        return round(float(ratings), 2)

    def cuisine(self) -> Optional[str]:
        cuisine = self.data.get("recipeCuisine")
        if isinstance(cuisine, list):
            return ",".join(cuisine)
        return cuisine
