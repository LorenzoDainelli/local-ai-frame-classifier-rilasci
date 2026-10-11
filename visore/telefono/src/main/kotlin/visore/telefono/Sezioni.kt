package visore.telefono

enum class Sezione(val comeSiChiama: String) {
    FOTO("Foto"),
    NODI("Nodi"),
    PERSONE("Persone"),
    CERCA("Cerca");

    companion object {

        val PRIMA = FOTO

        val quante: Int
            get() = entries.size
    }
}
