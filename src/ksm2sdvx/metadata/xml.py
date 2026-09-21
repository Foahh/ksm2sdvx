"""Immutable XML elements for generated target metadata."""

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from ksm2sdvx.metadata.errors import MetadataError


@dataclass(frozen=True, slots=True)
class XmlElement:
    name: str
    attributes: tuple[tuple[str, str], ...] = ()
    text: str | None = None
    children: tuple[XmlElement, ...] = ()

    def child(self, name: str) -> XmlElement:
        matches = tuple(child for child in self.children if child.name == name)
        if len(matches) != 1:
            raise MetadataError(f"Expected exactly one {name!r} element in {self.name!r}")
        return matches[0]


def from_element(element: ET.Element[str]) -> XmlElement:
    text = element.text if element.text and element.text.strip() else None
    return XmlElement(
        element.tag,
        tuple(element.attrib.items()),
        text,
        tuple(from_element(child) for child in element),
    )


def to_element(element: XmlElement) -> ET.Element[str]:
    result = ET.Element(element.name, dict(element.attributes))
    result.text = element.text
    result.extend(to_element(child) for child in element.children)
    return result
