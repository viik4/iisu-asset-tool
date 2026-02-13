package com.iisu.assettool.data

/**
 * Supported gaming platforms for artwork scraping.
 * Matches the platforms from the desktop Python version.
 * iisuFolder matches the PLATFORM_TO_IISU_FOLDER mapping from rom_parser.py
 */
enum class Platform(val displayName: String, val searchId: String, val iisuFolder: String) {
    // Nintendo
    NES("NES", "nes", "nes"),
    SNES("SNES", "snes", "snes"),
    N64("Nintendo 64", "n64", "n64"),
    N64DD("Nintendo 64DD", "n64dd", "n64"),
    GAMECUBE("GameCube", "gamecube", "gc"),
    WII("Wii", "wii", "wii"),
    WII_U("Wii U", "wiiu", "wiiu"),
    SWITCH("Nintendo Switch", "switch", "switch"),
    GAMEBOY("Game Boy", "gb", "gb"),
    GAMEBOY_COLOR("Game Boy Color", "gbc", "gbc"),
    GBA("Game Boy Advance", "gba", "gba"),
    DS("Nintendo DS", "nds", "nds"),
    THREEDS("Nintendo 3DS", "3ds", "n3ds"),
    VIRTUAL_BOY("Virtual Boy", "vb", "vb"),

    // Sony
    PS1("PlayStation", "ps1", "ps1"),
    PS2("PlayStation 2", "ps2", "ps2"),
    PS3("PlayStation 3", "ps3", "ps3"),
    PS4("PlayStation 4", "ps4", "ps4"),
    PS5("PlayStation 5", "ps5", "ps5"),
    PSP("PSP", "psp", "psp"),
    VITA("PS Vita", "vita", "vita"),

    // Microsoft
    XBOX("Xbox", "xbox", "xbox"),
    XBOX360("Xbox 360", "xbox360", "xbox360"),
    XBOXONE("Xbox One", "xboxone", "xboxone"),
    XBOXSERIES("Xbox Series X|S", "xboxseries", "xboxseries"),

    // Sega
    MASTER_SYSTEM("Master System", "mastersystem", "ms"),
    GENESIS("Sega Genesis", "genesis", "genesis"),
    SEGA_CD("Sega CD", "segacd", "segacd"),
    SEGA_32X("Sega 32X", "32x", "32x"),
    SATURN("Sega Saturn", "saturn", "saturn"),
    DREAMCAST("Dreamcast", "dreamcast", "dreamcast"),
    GAMEGEAR("Game Gear", "gamegear", "gg"),

    // Neo Geo
    NEOGEO("Neo Geo", "neogeo", "neogeo"),
    NEOGEO_CD("Neo Geo CD", "neogeocd", "neogeocd"),
    NEOGEO_POCKET("Neo Geo Pocket", "ngp", "ngp"),
    NEOGEO_POCKET_COLOR("Neo Geo Pocket Color", "ngpc", "ngpc"),

    // Atari
    ATARI2600("Atari 2600", "atari2600", "atari2600"),
    ATARI5200("Atari 5200", "atari5200", "atari5200"),
    ATARI7800("Atari 7800", "atari7800", "atari7800"),
    ATARI_JAGUAR("Atari Jaguar", "jaguar", "jaguar"),
    ATARI_LYNX("Atari Lynx", "lynx", "lynx"),

    // Other
    ARCADE("Arcade", "arcade", "arcade"),
    MAME("MAME", "mame", "mame"),
    FBA("FinalBurn Alpha", "fba", "fba"),
    TURBOGRAFX("TurboGrafx-16", "tg16", "tg16"),
    TURBOGRAFX_CD("TurboGrafx-CD", "tgcd", "tgcd"),
    WONDERSWAN("WonderSwan", "ws", "ws"),
    WONDERSWAN_COLOR("WonderSwan Color", "wsc", "wsc"),
    COLECOVISION("ColecoVision", "coleco", "coleco"),
    INTELLIVISION("Intellivision", "intv", "intv"),
    PC("PC", "pc", "pc"),
    DOS("DOS", "dos", "dos"),
    SCUMMVM("ScummVM", "scummvm", "scummvm"),
    ANDROID("Android", "android", "android"),
}
