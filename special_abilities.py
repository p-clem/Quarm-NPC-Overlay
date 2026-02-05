SPECIAL_ABILITIES = {
    1: "Summon",
    2: "Enrage",
    3: "Rampage",
    4: "AreaRampage",
    5: "Flurry",
    6: "TripleAttack",
    7: "DualWield",
    8: "DisallowEquip",
    9: "BaneAttack",
    10: "MagicalAttack",
    11: "RangedAttack",
    12: "Unslowable",          # SlowImmunity
    13: "Unmezzable",          # MesmerizeImmunity
    14: "Uncharmable",         # CharmImmunity
    15: "Unstunable",          # StunImmunity
    16: "Unsnarable",          # SnareImmunity
    17: "Unfearable",          # FearImmunity
    18: "DispellImmunity",
    19: "MeleeImmunity",
    20: "MagicImmunity",
    21: "Immune to fleeing",   # FleeingImmunity
    22: "MeleeImmunityExceptBane",
    23: "Immune to melee except magical",  # MeleeImmunityExceptMagical
    24: "AggroImmunity",
    25: "BeingAggroImmunity",
    26: "CastingFromRangeImmunity",
    27: "FeignDeathImmunity",
    28: "TauntImmunity",
    29: "TunnelVision",
    30: "NoBuffHealFriends",
    31: "Immune to lull effects",  # PacifyImmunity
    32: "Leash",
    33: "Tether",
    34: "PermarootFlee",
    35: "HarmFromClientImmunity",
    36: "AlwaysFlee",
    37: "FleePercent",
    38: "AllowBeneficial",
    39: "DisableMelee",
    40: "NPCChaseDistance",
    41: "AllowedToTank",
    42: "ProximityAggro",
    43: "AlwaysCallHelp",
    44: "UseWarriorSkills",
    45: "AlwaysFleeLowCon",
    46: "NoLoitering",
    47: "BadFactionBlockHandin",
    48: "PCDeathblowCorpse",
    49: "CorpseCamper",
    50: "ReverseSlow",
    51: "HasteImmunity",
    52: "DisarmImmunity",
    53: "RiposteImmunity",
    54: "ProximityAggro2",
    # 55: "Max"  # usually not used as an ability
}


def parse_special_abilities_ids(entry: str) -> list[int]:
    """Parse a special_abilities DB string and return ordered ability IDs.

    Handles formats like:
    - "1,1^10,1^14,1"
    - "1^10:1,1^14" (params after ':' are ignored)
    """
    if not entry or entry.strip() == "":
        return []

    parts = [p.strip() for p in entry.split(',') if p.strip()]

    seen: set[int] = set()
    ordered: list[int] = []

    def _maybe_add(token: str) -> None:
        token = token.strip()
        if not token:
            return

        # Some DBs store params like "10:1"; keep just the numeric prefix.
        if ':' in token:
            token = token.split(':', 1)[0].strip()

        # Guard against weird tokens; accept leading digits only.
        num = ''
        for ch in token:
            if ch.isdigit():
                num += ch
            else:
                break
        if not num:
            return

        try:
            aid = int(num)
        except ValueError:
            return

        if aid in SPECIAL_ABILITIES and aid not in seen:
            seen.add(aid)
            ordered.append(aid)

    for part in parts:
        if '^' in part:
            for sub in part.split('^'):
                _maybe_add(sub)
        else:
            _maybe_add(part)

    return ordered


def parse_special_abilities(entry: str) -> str:
    """
    Parse a special_abilities DB string and return comma-separated friendly names.

    Example input: "1,1^2,1^5,1,5^10,1^12,1^13,1^14,1^15,1^16,1^17,1^21,1^23,1^31,1"
    Example output: "Summon, Enrage, Flurry, MagicalAttack, Unslowable, Unmezzable, Uncharmable, Unstunable, Unsnarable, Unfearable, Immune to fleeing, Immune to melee except magical, Immune to lull effects"
    """
    if not entry or entry.strip() == "":
        return ""

    # Split on commas
    parts = [p.strip() for p in entry.split(',') if p.strip()]

    # Get names for known abilities, preserve order of first appearance
    seen = set()
    ordered_names = []

    for part in parts:
        if '^' in part:
            subparts = part.split('^')
            for sub in subparts:
                try:
                    aid = int(sub)
                    if aid in SPECIAL_ABILITIES and aid not in seen:
                        seen.add(aid)
                        ordered_names.append(SPECIAL_ABILITIES[aid])
                except ValueError:
                    pass
        else:
            try:
                aid = int(part)
                if aid in SPECIAL_ABILITIES and aid not in seen:
                    seen.add(aid)
                    ordered_names.append(SPECIAL_ABILITIES[aid])
            except ValueError:
                pass

    # Join with comma and space (matching the website style)
    return ", ".join(ordered_names)