/* Diagnostic payload candidate only; no production admission. Entire range is
 * verified against the exact owner ROM by build.py before injection. */
MEMORY { rom (rx) : ORIGIN = 0x08EB0B20, LENGTH = 0x14000 }
SECTIONS {
    .text : { KEEP(*(.text.entry)) *(.text*) *(.rodata*) } > rom
    .data : { *(.data*) } > rom
    .bss : { *(.bss*) *(COMMON) } > rom
    ASSERT(SIZEOF(.data) == 0, "probe must not need data initialization")
    ASSERT(SIZEOF(.bss) == 0, "probe must not need BSS initialization")
    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment*) *(.note*) }
}
