package com.iisu.assettool.data

/**
 * Represents a game from SteamGridDB search results.
 * This is used in the Icon Generator to let users select which game they want artwork for.
 */
data class GameSearchResult(
    val id: Int,
    val name: String,
    val releaseYear: Int? = null,
    val types: List<String> = emptyList()  // e.g., ["steam", "origin"]
)
