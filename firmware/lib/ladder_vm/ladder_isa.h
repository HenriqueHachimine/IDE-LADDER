/* ARQUIVO GERADO por scripts/gen_isa_header.py a partir de
 * shared/specifications/isa.json. NAO EDITE MANUALMENTE. */
#ifndef LADDER_ISA_H
#define LADDER_ISA_H

#define LV_FMT_MAGIC "LDRB"
#define LV_FMT_MAJOR 2u
#define LV_FMT_MINOR 0u
#define LV_HEADER_SIZE 36u
#define LV_TIMER_ENTRY_SIZE 8u
#define LV_COUNTER_ENTRY_SIZE 8u
#define LV_CONSTANT_ENTRY_SIZE 4u
#define LV_INSTRUCTION_SIZE 4u
#define LV_CRC_SIZE 4u

#define LV_MAX_INPUTS 16u
#define LV_MAX_OUTPUTS 16u
#define LV_MAX_MARKERS 256u
#define LV_MAX_TIMERS 32u
#define LV_MAX_COUNTERS 32u
#define LV_MAX_WORDS 64u
#define LV_MAX_CONSTANTS 128u
#define LV_MAX_RUNGS 256u
#define LV_MAX_INSTRUCTIONS 2048u
#define LV_MAX_BRANCH_DEPTH 8u
#define LV_MAX_PRESET 2147483647u
#define LV_SYSTEM_BITS 7u
#define LV_MAX_IMAGE_SIZE (LV_HEADER_SIZE + LV_MAX_TIMERS * LV_TIMER_ENTRY_SIZE + \
    LV_MAX_COUNTERS * LV_COUNTER_ENTRY_SIZE + LV_MAX_CONSTANTS * LV_CONSTANT_ENTRY_SIZE + \
    LV_MAX_INSTRUCTIONS * LV_INSTRUCTION_SIZE + LV_CRC_SIZE)

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
#define LV_AREA_N 13u
#define LV_AREA_K 14u
#define LV_AREA_T_ACC 15u
#define LV_AREA_T_PRE 16u
#define LV_AREA_C_ACC 17u
#define LV_AREA_C_PRE 18u
#define LV_AREA_IW 19u
#define LV_AREA_QW 20u

/* Bits de sistema (area S) */
#define LV_SYS_FIRST_SCAN 0u
#define LV_SYS_ALWAYS_ON 1u
#define LV_SYS_ALWAYS_OFF 2u
#define LV_SYS_CLOCK_1S 3u
#define LV_SYS_MATH_OV 4u
#define LV_SYS_MATH_ZERO 5u
#define LV_SYS_MATH_SIGN 6u

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
#define LV_OP_EQU 96u
#define LV_OP_NEQ 97u
#define LV_OP_LES 98u
#define LV_OP_GRT 99u
#define LV_OP_LEQ 100u
#define LV_OP_GEQ 101u
#define LV_OP_LIM 102u
#define LV_OP_MEQ 103u
#define LV_OP_ADD 104u
#define LV_OP_SUB 105u
#define LV_OP_MUL 106u
#define LV_OP_DIV 107u
#define LV_OP_SQR 108u
#define LV_OP_NEG 109u
#define LV_OP_TOD 110u
#define LV_OP_FRD 111u
#define LV_OP_ARG 112u

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
    LV_OPERAND_WORD_READ = 6,
    LV_OPERAND_WORD_WRITE = 7,
    LV_OPERAND_ARG = 8,
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
    case LV_OP_EQU: return LV_OPERAND_WORD_READ;
    case LV_OP_NEQ: return LV_OPERAND_WORD_READ;
    case LV_OP_LES: return LV_OPERAND_WORD_READ;
    case LV_OP_GRT: return LV_OPERAND_WORD_READ;
    case LV_OP_LEQ: return LV_OPERAND_WORD_READ;
    case LV_OP_GEQ: return LV_OPERAND_WORD_READ;
    case LV_OP_LIM: return LV_OPERAND_WORD_READ;
    case LV_OP_MEQ: return LV_OPERAND_WORD_READ;
    case LV_OP_ADD: return LV_OPERAND_WORD_READ;
    case LV_OP_SUB: return LV_OPERAND_WORD_READ;
    case LV_OP_MUL: return LV_OPERAND_WORD_READ;
    case LV_OP_DIV: return LV_OPERAND_WORD_READ;
    case LV_OP_SQR: return LV_OPERAND_WORD_READ;
    case LV_OP_NEG: return LV_OPERAND_WORD_READ;
    case LV_OP_TOD: return LV_OPERAND_WORD_READ;
    case LV_OP_FRD: return LV_OPERAND_WORD_READ;
    case LV_OP_ARG: return LV_OPERAND_ARG;
    default: return LV_OPERAND_INVALID;
    }
}

/* Numero de instrucoes ARG que seguem a instrucao (operandos adicionais). */
static inline unsigned lv_arg_count(unsigned opcode)
{
    switch (opcode) {
    case LV_OP_EQU: return 1u;
    case LV_OP_NEQ: return 1u;
    case LV_OP_LES: return 1u;
    case LV_OP_GRT: return 1u;
    case LV_OP_LEQ: return 1u;
    case LV_OP_GEQ: return 1u;
    case LV_OP_LIM: return 2u;
    case LV_OP_MEQ: return 2u;
    case LV_OP_ADD: return 2u;
    case LV_OP_SUB: return 2u;
    case LV_OP_MUL: return 2u;
    case LV_OP_DIV: return 2u;
    case LV_OP_SQR: return 1u;
    case LV_OP_NEG: return 1u;
    case LV_OP_TOD: return 1u;
    case LV_OP_FRD: return 1u;
    default: return 0u;
    }
}

/* Classe do k-esimo operando adicional (k = 0 e o primeiro ARG). */
static inline lv_operand_class_t lv_arg_class(unsigned opcode, unsigned k)
{
    switch (opcode) {
    case LV_OP_EQU: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_NEQ: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_LES: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_GRT: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_LEQ: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_GEQ: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_LIM: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ, LV_OPERAND_WORD_READ}; return k < 2u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_MEQ: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ, LV_OPERAND_WORD_READ}; return k < 2u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_ADD: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ, LV_OPERAND_WORD_WRITE}; return k < 2u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_SUB: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ, LV_OPERAND_WORD_WRITE}; return k < 2u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_MUL: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ, LV_OPERAND_WORD_WRITE}; return k < 2u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_DIV: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_READ, LV_OPERAND_WORD_WRITE}; return k < 2u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_SQR: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_WRITE}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_NEG: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_WRITE}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_TOD: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_WRITE}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
    case LV_OP_FRD: { static const lv_operand_class_t c[] = {LV_OPERAND_WORD_WRITE}; return k < 1u ? c[k] : LV_OPERAND_INVALID; }
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
    case LV_OP_EQU: return "EQU";
    case LV_OP_NEQ: return "NEQ";
    case LV_OP_LES: return "LES";
    case LV_OP_GRT: return "GRT";
    case LV_OP_LEQ: return "LEQ";
    case LV_OP_GEQ: return "GEQ";
    case LV_OP_LIM: return "LIM";
    case LV_OP_MEQ: return "MEQ";
    case LV_OP_ADD: return "ADD";
    case LV_OP_SUB: return "SUB";
    case LV_OP_MUL: return "MUL";
    case LV_OP_DIV: return "DIV";
    case LV_OP_SQR: return "SQR";
    case LV_OP_NEG: return "NEG";
    case LV_OP_TOD: return "TOD";
    case LV_OP_FRD: return "FRD";
    case LV_OP_ARG: return "ARG";
    default: return "?";
    }
}

#endif /* LADDER_ISA_H */
