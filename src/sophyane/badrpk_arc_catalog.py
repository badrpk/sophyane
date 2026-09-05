"""Public BADRPK repository catalog used as bounded ARC provenance."""
PUBLIC_REPOSITORIES = {
 "sophyane":"orchestration and validation", "Cosmos":"control plane", "shmry":"cloud and storage",
 "nifdu":"rendered verification and screenshot evidence", "neuron":"temporal neural computation",
 "Aivra":"AI execution", "Portis":"network services", "huobz":"AI and systems research",
 "rangoons":"commerce", "cast":"media delivery", "Lumera":"real-time energy", "Lyvera":"application experience",
 "xerus":"disk-first memory and retrieval", "Lexane":"compact semantic language", "Voltara":"energy platform",
 "Pactra":"fleet mobility", "Chrona":"historical content", "Rydea":"field mobility", "Sakina":"care platform",
 "Avyra":"web application", "Mivra":"mobile interface", "Rivora":"real-time service", "Edryx":"edge execution",
 "Algora":"algorithmic reasoning", "Voxara":"content distribution", "Nimora":"NIFDU-backed presentation",
 "Droidra":"Android workspace", "Savora":"food commerce", "Medora":"digital health", "Rangora":"service layer",
 "Codane":"coding automation", "Veyron":"native transport",
}
ARC_ACTIVE = ("sophyane", "nifdu", "neuron", "xerus", "Algora", "Lexane", "Aivra", "Edryx")

def bounded_catalog():
    return {"public_repository_count":len(PUBLIC_REPOSITORIES), "repositories":PUBLIC_REPOSITORIES,
            "arc_active_candidates":ARC_ACTIVE,
            "authority":"provenance only; names cannot select actions or assert outcomes"}
