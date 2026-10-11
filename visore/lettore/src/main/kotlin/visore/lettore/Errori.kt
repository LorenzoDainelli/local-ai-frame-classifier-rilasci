package visore.lettore

open class ErroreVisore(
    val frase: String,
    val codice: String = "",
) : Exception(frase)

class PasswordSbagliata(frase: String) : ErroreVisore(frase, "password_sbagliata")

class PacchettoRovinato(frase: String) : ErroreVisore(frase, "pacchetto_rovinato")
