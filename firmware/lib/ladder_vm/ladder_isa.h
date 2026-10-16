/* ARQUIVO GERADO por scripts/gen_isa_header.py a partir de
 * shared/specifications/isa.json. NAO EDITE MANUALMENTE. */
#ifndef LADDER_ISA_H
#define LADDER_ISA_H

#define LV_FMT_MAGIC "LDRB"
#define LV_FMT_MAJOR 1u
#define LV_FMT_MINOR 0u
#define LV_HEADER_SIZE 32u
#define LV_TIMER_ENTRY_SIZE 8u
#define LV_COUNTER_ENTRY_SIZE 8u
#define LV_INSTRUCTION_SIZE 4u
#define LV_CRC_SIZE 4u

#define LV_MAX_INPUTS 16u
#define LV_MAX_OUTPUTS 16u
#define LV_MAX_MARKERS 256u
#define LV_MAX_TIMERS 32u
#define LV_MAX_COUNTERS 32u
#define LV_MAX_RUNGS 256u
#define LV_MAX_INSTRUCTIONS 2048u
#define LV_MAX_BRANCH_DEPTH 8u
#define LV_MAX_PRESET 2147483647u
#define LV_SYSTEM_BITS 4u
#define LV_MAX_IMAGE_SIZE (LV_HEADER_SIZE + LV_MAX_TIMERS * LV_TIMER_ENTRY_SIZE + \
    LV_MAX_COUNTERS * LV_COUNTER_ENTRY_SIZE + LV_MAX_INSTRUCTIONS * LV_INSTRUCTION_SIZE + LV_CRC_SIZE)

/* Areas de operando */
#define LV_AREA_NONE 0u
#define LV_AREA_I 1u
#define LV_AREA_Q 2u
#define LV_AREA_M 3u
#define LV_AREA_S 4u
#define LV_AREA_T_EN 5u
#define LV_AREA_T_TT 6u
#define LV_AREA_T_DN 7u
#define LV_AREA_C_DN 8u
#define LV_AREA_C_OV 9u
#define LV_AREA_C_UN 10u
#define LV_AREA_TIMER 11u
#define LV_AREA_COUNTER 12u

/* Bits de sistema (area S) */
#define LV_SYS_FIRST_SCAN 0u
#define LV_SYS_ALWAYS_ON 1u
#define LV_SYS_ALWAYS_OFF 2u
#define LV_SYS_CLOCK_1S 3u

/* Opcodes */
#define LV_OP_SOR 1u
#define LV_OP_EOR 2u
#define LV_OP_XIC 16u
#define LV_OP_XIO 17u
#define LV_OP_NOT 18u
#define LV_OP_BST 32u
#define LV_OP_NXB 33u
#define LV_OP_BND 34u
#define LV_OP_OTE 48u
#define LV_OP_OTL 49u
#define LV_OP_OTU 50u
#define LV_OP_TON 64u
#define LV_OP_TOF 65u
#define LV_OP_RTO 66u
#define LV_OP_CTU 72u
#define LV_OP_CTD 73u
#define LV_OP_RES 80u

/* Tipos de temporizador e contador */
#define LV_TIMER_TON 0u
#define LV_TIMER_TOF 1u
#define LV_TIMER_RTO 2u
#define LV_COUNTER_UP 0u
#define LV_COUNTER_DOWN 1u

/* Codigos de erro de validacao de imagem */
typedef enum {
    LV_ERR_OK = 0,
    LV_ERR_TOO_SHORT = 1,
    LV_ERR_BAD_MAGIC = 2,
    LV_ERR_UNSUPPORTED_VERSION = 3,
    LV_ERR_BAD_HEADER_SIZE = 4,
    LV_ERR_SIZE_MISMATCH = 5,
    LV_ERR_BAD_CRC = 6,
    LV_ERR_LIMIT_EXCEEDED = 7,
    LV_ERR_BAD_TIMER_TABLE = 8,
    LV_ERR_BAD_COUNTER_TABLE = 9,
    LV_ERR_BAD_OPCODE = 10,
    LV_ERR_BAD_OPERAND = 11,
    LV_ERR_BAD_STRUCTURE = 12,
    LV_ERR_BRANCH_ERROR = 13,
    LV_ERR_DUPLICATE_DRIVER = 14,
    LV_ERR_TYPE_MISMATCH = 15,
    LV_ERR_RESERVED_NONZERO = 16,
} lv_image_error_t;

/* Classes de operando */
typedef enum {
    LV_OPERAND_NONE = 0,
    LV_OPERAND_BIT_READ = 1,
    LV_OPERAND_BIT_WRITE = 2,
    LV_OPERAND_TIMER = 3,
    LV_OPERAND_COUNTER = 4,
    LV_OPERAND_TIMER_OR_COUNTER = 5,
    LV_OPERAND_INVALID = -1
} lv_operand_class_t;

static inline lv_operand_class_t lv_operand_class(unsigned opcode)
{
    switch (opcode) {
    case LV_OP_SOR: return LV_OPERAND_NONE;
    case LV_OP_EOR: return LV_OPERAND_NONE;
    case LV_OP_XIC: return LV_OPERAND_BIT_READ;
    case LV_OP_XIO: return LV_OPERAND_BIT_READ;
    case LV_OP_NOT: return LV_OPERAND_NONE;
    case LV_OP_BST: return LV_OPERAND_NONE;
    case LV_OP_NXB: return LV_OPERAND_NONE;
    case LV_OP_BND: return LV_OPERAND_NONE;
    case LV_OP_OTE: return LV_OPERAND_BIT_WRITE;
    case LV_OP_OTL: return LV_OPERAND_BIT_WRITE;
    case LV_OP_OTU: return LV_OPERAND_BIT_WRITE;
    case LV_OP_TON: return LV_OPERAND_TIMER;
    case LV_OP_TOF: return LV_OPERAND_TIMER;
    case LV_OP_RTO: return LV_OPERAND_TIMER;
    case LV_OP_CTU: return LV_OPERAND_COUNTER;
    case LV_OP_CTD: return LV_OPERAND_COUNTER;
    case LV_OP_RES: return LV_OPERAND_TIMER_OR_COUNTER;
    default: return LV_OPERAND_INVALID;
    }
}

static inline const char *lv_opcode_name(unsigned opcode)
{
    switch (opcode) {
    case LV_OP_SOR: return "SOR";
    case LV_OP_EOR: return "EOR";
    case LV_OP_XIC: return "XIC";
    case LV_OP_XIO: return "XIO";
    case LV_OP_NOT: return "NOT";
    case LV_OP_BST: return "BST";
    case LV_OP_NXB: return "NXB";
    case LV_OP_BND: return "BND";
    case LV_OP_OTE: return "OTE";
    case LV_OP_OTL: return "OTL";
    case LV_OP_OTU: return "OTU";
    case LV_OP_TON: return "TON";
    case LV_OP_TOF: return "TOF";
    case LV_OP_RTO: return "RTO";
    case LV_OP_CTU: return "CTU";
    case LV_OP_CTD: return "CTD";
    case LV_OP_RES: return "RES";
    default: return "?";
    }
}

#endif /* LADDER_ISA_H */
