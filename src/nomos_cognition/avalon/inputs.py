"""Build model observations from explicit values, with no Session or world access."""

from .observations import ROLES, Advice, Ballot, Claim, Observation, Proposal, Quest


def observation(values):
    if len(values["population"]) != 1 or len(values["identity"]) != 1:
        raise ValueError("model requires one acquired population and own identity")
    population, identity = values["population"][0], values["identity"][0]
    if len(population.roster) != 5 or sorted(population.cast) != sorted(ROLES):
        raise ValueError("model selects exactly the five declared distinct roles")
    roster = tuple(sorted(population.roster, key=lambda ref: ref.ordinal))
    indexes = {ref: index for index, ref in enumerate(roster)}
    if identity.subject != values["observer"]:
        raise ValueError("model identity must describe its observer")

    def group(items):
        return tuple(sorted(indexes[item] for item in items))

    known = set()
    for members in (*values["peers"], *values["suspects"]):
        known.update(group(members))
    pairs = values["pairs"]
    if len(pairs) > 1 or pairs and sorted(pairs[0].labels) != ["merlin", "morgana"]:
        raise ValueError("model candidate pair differs from its selected contract")
    proposals = {
        row.epoch: Proposal(row.epoch, indexes[row.leader], group(row.team))
        for row in values["approvals"]
    }
    if values["epoch"] > 0 and values["team"]:
        proposals.setdefault(
            values["epoch"],
            Proposal(values["epoch"], indexes[values["leader"]], group(values["team"])),
        )
    return roster, Observation(
        indexes[identity.subject],
        identity.role,
        tuple(sorted(known)),
        None if not pairs else group(pairs[0].subjects),
        proposals=tuple(proposals.values()),
        ballots=tuple(
            Ballot(r.epoch, group(r.team), group(r.approve)) for r in values["approvals"]
        ),
        quests=tuple(Quest(r.epoch, group(r.team), r.fails) for r in values["quests"]),
        claims=tuple(Claim(indexes[r.speaker], r.role) for r in values["claims"]),
        advice=tuple(
            Advice(indexes[r.speaker], group(r.team), r.approve) for r in values["advice"]
        ),
    )
