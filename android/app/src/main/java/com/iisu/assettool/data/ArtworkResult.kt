package com.iisu.assettool.data

/**
 * Represents an artwork search result from web scraping.
 */
data class ArtworkResult(
    val url: String,
    val title: String,
    val platform: Platform,
    val type: ArtworkType,
    val width: Int = 0,
    val height: Int = 0,
    val source: String = "",
    val score: Int = 0
)

enum class ArtworkType {
    ICON,
    COVER,
    SCREENSHOT,
    FANART,
    HERO,
    LOGO
}
