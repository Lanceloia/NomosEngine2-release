"""Shared closed Source section grammar for checking and file assembly."""

SOURCE_SCHEMA = "c0.owner_graph.v6"
SOURCE_REQUIRED = frozenset(
    {
        "schema",
        "owners",
        "lawdefs",
        "actions",
        "events",
        "seats",
        "offer_provider",
        "game_form",
    }
)
SOURCE_LIST_SECTIONS = frozenset(
    {
        "owners",
        "lawdefs",
        "actions",
        "events",
        "seats",
        "actor_domains",
        "due_events",
        "object_kinds",
        "operation_bindings",
        "appraisal_profiles",
        "actor_templates",
        "opening_constructions",
        "participant_bindings",
        "offer_sets",
    }
)
SOURCE_SINGLETON_SECTIONS = frozenset(
    {
        "opening_guard",
        "opening_actor_guards",
        "game_form",
        "temporal",
        "ontology",
        "offer_provider",
    }
)
SOURCE_SECTIONS = SOURCE_LIST_SECTIONS | SOURCE_SINGLETON_SECTIONS
