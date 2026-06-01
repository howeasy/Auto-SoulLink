/* Place SLink injected code at the free-ROM region; slink_hook() must be first
 * (the CallCallbacks hook BLs to CODE_BASE). */
MEMORY { rom (rx) : ORIGIN = 0x08378CA8, LENGTH = 0x14000 }

SECTIONS
{
  .text 0x08378CA8 :
  {
    KEEP(*(.text.entry))   /* slink_hook lands exactly at CODE_BASE */
    *(.text*)
    *(.rodata*)
    *(.data*)
  } > rom

  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) *(.note*) }
}
