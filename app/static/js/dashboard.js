/* ==========================================================================
   GoldenKnight dashboard - bediening van alle onderdelen.
   ========================================================================== */

(function () {
    "use strict";

    var instellingen = document.getElementById("dashboard-config");
    var VERVERS_MS = parseInt(instellingen.dataset.verversMs, 10) || 2000;
    var CSRF = instellingen.dataset.csrf;
    var WEER_AAN = instellingen.dataset.weerAan === "ja";
    var periode = instellingen.dataset.periode || "24u";

    var SERIEKLEUREN = ["--serie-1", "--serie-2", "--serie-3"];

    /* ===================== Hulpmiddelen ================================== */

    function $(selector, binnen) {
        return (binnen || document).querySelector(selector);
    }

    function alle(selector, binnen) {
        return Array.prototype.slice.call((binnen || document).querySelectorAll(selector));
    }

    function kleurVan(index) {
        return getComputedStyle(document.documentElement)
            .getPropertyValue(SERIEKLEUREN[index % SERIEKLEUREN.length]).trim() || "#2a78d6";
    }

    function getal(waarde, decimalen) {
        if (waarde === null || waarde === undefined || waarde === "" || isNaN(waarde)) {
            return "--";
        }
        return Number(waarde).toLocaleString("nl-NL", {
            minimumFractionDigits: decimalen,
            maximumFractionDigits: decimalen
        });
    }

    function tekstIn(element, tekst) {
        if (element) { element.textContent = tekst; }
    }

    function toonMelding(element, tekst, soort) {
        if (!element) { return; }
        element.textContent = tekst;
        element.className = "melding" + (soort ? " melding-" + soort : "");
        element.hidden = !tekst;
    }

    /** fetch met JSON, CSRF-token en nette foutafhandeling. */
    function api(pad, opties) {
        opties = opties || {};
        var kop = { "Accept": "application/json" };
        if (opties.json !== undefined) {
            kop["Content-Type"] = "application/json";
            opties.body = JSON.stringify(opties.json);
        }
        if ((opties.method || "GET") !== "GET") {
            kop["X-CSRF-Token"] = CSRF;
        }
        return fetch(pad, {
            method: opties.method || "GET",
            headers: kop,
            body: opties.body,
            credentials: "same-origin"
        }).then(function (antwoord) {
            if (antwoord.status === 401) {
                window.location.href = "/inloggen";
                throw new Error("niet ingelogd");
            }
            return antwoord.json().catch(function () { return {}; }).then(function (data) {
                if (!antwoord.ok) {
                    throw new Error(data.melding || "Er ging iets mis (" + antwoord.status + ").");
                }
                return data;
            });
        });
    }

    /* ===================== Sensorkaarten ================================= */

    var statusStip = $("#status-stip");
    var statusTekst = $("#status-tekst");

    function verversSensoren() {
        return api("/api/sensor").then(function (data) {
            tekstIn($("#temperature"), getal(data.temperature, 1));
            tekstIn($("#humidity"), getal(data.humidity, 1));
            tekstIn($("#light"), getal(data.light, 0));
            tekstIn($("#timestamp"), "Laatste update: " + (data.timestamp || "--"));

            statusStip.className = "stip " + (data.live ? "live" : "simulatie");
            tekstIn(statusTekst, data.bron_omschrijving || "Sensordata");
        }).catch(function () {
            statusStip.className = "stip fout";
            tekstIn(statusTekst, "Geen verbinding met de sensor-API");
            tekstIn($("#timestamp"), "Kan geen verbinding maken met de sensor API");
        });
    }

    /* ===================== Grafieken ===================================== */

    var grafieken = [];
    var laatsteGeschiedenis = null;

    function maakGrafieken() {
        alle(".grafiekkaart").forEach(function (kaart, index) {
            var vlak = $('[data-rol="grafiek"]', kaart);
            var sleutel = kaart.dataset.metriek;
            var decimalen = sleutel === "light" ? 0 : 1;
            var eenheid = sleutel === "temperature" ? "°C" : (sleutel === "humidity" ? "%" : "");
            grafieken.push({
                sleutel: sleutel,
                kaart: kaart,
                decimalen: decimalen,
                eenheid: eenheid,
                index: index,
                grafiek: new Lijngrafiek(vlak, {
                    kleur: kleurVan(index),
                    eenheid: eenheid,
                    decimalen: decimalen
                })
            });
        });
    }

    function tekenGeschiedenis(data) {
        laatsteGeschiedenis = data;

        grafieken.forEach(function (item) {
            item.grafiek.opties.kleur = kleurVan(item.index);
            item.grafiek.zet(data.punten.map(function (punt) {
                return {
                    tijd: new Date(punt.tijd),
                    waarde: punt[item.sleutel]
                };
            }));

            var samenvatting = (data.samenvatting || {})[item.sleutel] || {};
            var laatste = null;
            for (var i = data.punten.length - 1; i >= 0; i -= 1) {
                if (data.punten[i][item.sleutel] !== null) {
                    laatste = data.punten[i][item.sleutel];
                    break;
                }
            }
            var achtervoegsel = item.eenheid ? " " + item.eenheid : "";
            tekstIn($('[data-rol="huidig"]', item.kaart),
                getal(laatste, item.decimalen) + achtervoegsel);
            tekstIn($('[data-rol="min"]', item.kaart),
                "min " + getal(samenvatting.min, item.decimalen));
            tekstIn($('[data-rol="gem"]', item.kaart),
                "gem " + getal(samenvatting.gemiddelde, item.decimalen));
            tekstIn($('[data-rol="max"]', item.kaart),
                "max " + getal(samenvatting.max, item.decimalen));
        });

        tekstIn($("#grafiek-uitleg"),
            data.aantal > 0
                ? data.label + " - " + data.samenvatting.metingen +
                  " metingen, gemiddeld per " + minutenTekst(data.vakgrootte_seconden) + "."
                : data.label + " - nog geen metingen bewaard. De eerste punten " +
                  "verschijnen zodra de metingen binnenkomen.");

        vulTabel(data);
    }

    function minutenTekst(seconden) {
        if (seconden < 60) {
            return seconden + (seconden === 1 ? " seconde" : " seconden");
        }
        var minuten = Math.round(seconden / 60);
        if (minuten < 60) {
            return minuten + (minuten === 1 ? " minuut" : " minuten");
        }
        return Math.round(minuten / 60) + " uur";
    }

    function vulTabel(data) {
        var lichaam = $("#grafiek-tabel-inhoud");
        lichaam.textContent = "";
        data.punten.slice().reverse().forEach(function (punt) {
            var rij = document.createElement("tr");
            var tijdCel = document.createElement("td");
            tijdCel.textContent = window.grafiekHulp.tijdVolledig(new Date(punt.tijd));
            rij.appendChild(tijdCel);
            [["temperature", 1], ["humidity", 1], ["light", 0]].forEach(function (paar) {
                var cel = document.createElement("td");
                cel.textContent = getal(punt[paar[0]], paar[1]);
                rij.appendChild(cel);
            });
            lichaam.appendChild(rij);
        });
    }

    function verversGeschiedenis() {
        return api("/api/history?periode=" + encodeURIComponent(periode))
            .then(tekenGeschiedenis)
            .catch(function () { /* stil: de volgende ronde probeert het opnieuw */ });
    }

    function koppelGrafiekknoppen() {
        alle("#grafieken .filterknop[data-periode]").forEach(function (knop) {
            knop.addEventListener("click", function () {
                alle("#grafieken .filterknop[data-periode]").forEach(function (andere) {
                    andere.classList.remove("actief");
                });
                knop.classList.add("actief");
                periode = knop.dataset.periode;
                verversGeschiedenis();
            });
        });

        var schakelaar = $("#tabel-schakelaar");
        schakelaar.addEventListener("click", function () {
            var tabel = $("#grafiek-tabel");
            var wordtZichtbaar = tabel.hidden;
            tabel.hidden = !wordtZichtbaar;
            schakelaar.setAttribute("aria-pressed", wordtZichtbaar ? "true" : "false");
        });
    }

    /* ===================== Weer ========================================== */

    var weerGrafiek = null;

    function verversWeer(forceren) {
        if (!WEER_AAN) { return Promise.resolve(); }
        return api("/api/weer" + (forceren ? "?ververs=1" : "")).then(function (data) {
            var melding = $("#weer-melding");
            var nuBlok = $("#weer-nu");
            var grafiekFiguur = $("#weer-grafiek-figuur");

            if (!data.beschikbaar) {
                nuBlok.hidden = true;
                grafiekFiguur.hidden = true;
                $("#weer-dagen").textContent = "";
                toonMelding(melding, data.melding || "Geen weergegevens.", "fout");
                melding.hidden = false;
                return;
            }

            if (data.verouderd) {
                toonMelding(melding, data.melding, "fout");
            } else {
                melding.hidden = true;
            }

            nuBlok.hidden = false;
            var nu = data.nu || {};
            tekstIn($("#weer-icoon"), nu.icoon || "");
            tekstIn($("#weer-temperatuur"), getal(nu.temperatuur, 1));
            tekstIn($("#weer-omschrijving"), nu.omschrijving || "--");
            tekstIn($("#weer-plaats"), data.plaats || "");
            tekstIn($("#weer-gevoel"), getal(nu.gevoel, 1) + " °C");
            tekstIn($("#weer-wind"), getal(nu.wind, 0) + " km/u " + (nu.windrichting || ""));
            tekstIn($("#weer-neerslag"), getal(nu.neerslag, 1) + " mm");
            tekstIn($("#weer-vocht"), getal(nu.luchtvochtigheid, 0) + " %");
            tekstIn($("#weer-zon-op"), data.zonsopkomst || "--");
            tekstIn($("#weer-zon-onder"), data.zonsondergang || "--");

            var dagenHouder = $("#weer-dagen");
            dagenHouder.textContent = "";
            (data.dagen || []).forEach(function (dag) {
                var blok = document.createElement("div");
                blok.className = "weer-dag";

                var naam = document.createElement("div");
                naam.className = "dag";
                naam.textContent = dag.dag;

                var icoon = document.createElement("span");
                icoon.className = "icoon";
                icoon.setAttribute("aria-hidden", "true");
                icoon.textContent = dag.icoon;

                var temps = document.createElement("div");
                temps.className = "temps";
                temps.appendChild(document.createTextNode(getal(dag.max, 0) + "° "));
                var minimum = document.createElement("span");
                minimum.className = "min";
                minimum.textContent = getal(dag.min, 0) + "°";
                temps.appendChild(minimum);

                var omschrijving = document.createElement("div");
                omschrijving.className = "neerslag";
                omschrijving.textContent = dag.omschrijving;

                blok.appendChild(naam);
                blok.appendChild(icoon);
                blok.appendChild(temps);
                blok.appendChild(omschrijving);
                blok.title = dag.omschrijving + " - neerslag " + getal(dag.neerslag, 1) + " mm";
                dagenHouder.appendChild(blok);
            });

            var uren = data.uren || [];
            if (uren.length > 1) {
                grafiekFiguur.hidden = false;
                if (!weerGrafiek) {
                    weerGrafiek = new Lijngrafiek($("#weer-grafiek"), {
                        kleur: kleurVan(0), eenheid: "°C", decimalen: 1, hoogte: 150
                    });
                }
                weerGrafiek.opties.kleur = kleurVan(0);
                weerGrafiek.zet(uren.map(function (uur) {
                    return { tijd: new Date(uur.tijd), waarde: uur.temperatuur };
                }));
            } else {
                grafiekFiguur.hidden = true;
            }
        }).catch(function (fout) {
            toonMelding($("#weer-melding"), fout.message, "fout");
        });
    }

    /* ===================== Backlog ======================================= */

    var backlogFilter = "alle";

    function verversBacklog() {
        var pad = "/api/backlog";
        if (backlogFilter !== "alle") {
            pad += "?status=" + encodeURIComponent(backlogFilter);
        }
        return api(pad).then(tekenBacklog).catch(function (fout) {
            toonMelding($("#backlog-melding"), fout.message, "fout");
        });
    }

    function tekenBacklog(data) {
        var tellers = $("#backlog-tellers");
        tellers.textContent = "";
        var namen = { todo: "Te doen", bezig: "Mee bezig", klaar: "Klaar" };
        Object.keys(namen).forEach(function (sleutel) {
            var chip = document.createElement("span");
            chip.className = "teller";
            chip.textContent = namen[sleutel] + ": " + (data.tellingen[sleutel] || 0);
            tellers.appendChild(chip);
        });

        var lijst = $("#backlog-lijst");
        lijst.textContent = "";

        if (!data.items.length) {
            var leeg = document.createElement("li");
            leeg.className = "leeg";
            leeg.textContent = backlogFilter === "alle"
                ? "De backlog is leeg. Voeg hierboven je eerste taak toe."
                : "Geen taken met deze status.";
            lijst.appendChild(leeg);
            return;
        }

        data.items.forEach(function (item) {
            lijst.appendChild(maakBacklogItem(item));
        });
    }

    function maakBacklogItem(item) {
        var regel = document.createElement("li");
        regel.className = "backlog-item" + (item.status === "klaar" ? " klaar" : "");

        var inhoud = document.createElement("div");
        inhoud.className = "backlog-inhoud";

        var titel = document.createElement("div");
        titel.className = "backlog-titel";
        titel.textContent = item.titel;
        inhoud.appendChild(titel);

        if (item.omschrijving) {
            var omschrijving = document.createElement("div");
            omschrijving.className = "backlog-omschrijving";
            omschrijving.textContent = item.omschrijving;
            inhoud.appendChild(omschrijving);
        }

        var meta = document.createElement("div");
        meta.className = "backlog-meta";

        var prioriteit = document.createElement("span");
        prioriteit.className = "merk merk-" + item.prioriteit;
        prioriteit.textContent = "Prioriteit: " + item.prioriteit_naam;
        meta.appendChild(prioriteit);

        var status = document.createElement("span");
        status.className = "merk";
        status.textContent = item.status_naam;
        meta.appendChild(status);

        if (item.deadline) {
            var vandaag = new Date().toISOString().slice(0, 10);
            var verlopen = item.status !== "klaar" && item.deadline < vandaag;
            var deadline = document.createElement("span");
            deadline.className = "merk" + (verlopen ? " merk-verlopen" : "");
            deadline.textContent = (verlopen ? "Te laat: " : "Deadline: ") +
                datumNl(item.deadline);
            meta.appendChild(deadline);
        }

        inhoud.appendChild(meta);
        regel.appendChild(inhoud);

        var knoppen = document.createElement("div");
        knoppen.className = "backlog-knoppen";
        [["todo", "Te doen"], ["bezig", "Bezig"], ["klaar", "Klaar"]].forEach(function (paar) {
            var knop = document.createElement("button");
            knop.type = "button";
            knop.className = "mini-knop" + (item.status === paar[0] ? " actief" : "");
            knop.textContent = paar[1];
            knop.addEventListener("click", function () {
                api("/api/backlog/" + item.id, { method: "PATCH", json: { status: paar[0] } })
                    .then(verversBacklog)
                    .catch(function (fout) {
                        toonMelding($("#backlog-melding"), fout.message, "fout");
                    });
            });
            knoppen.appendChild(knop);
        });

        var verwijder = document.createElement("button");
        verwijder.type = "button";
        verwijder.className = "mini-knop verwijder";
        verwijder.textContent = "Verwijderen";
        verwijder.addEventListener("click", function () {
            if (!window.confirm('Taak "' + item.titel + '" verwijderen?')) { return; }
            api("/api/backlog/" + item.id, { method: "DELETE" })
                .then(verversBacklog)
                .catch(function (fout) {
                    toonMelding($("#backlog-melding"), fout.message, "fout");
                });
        });
        knoppen.appendChild(verwijder);

        regel.appendChild(knoppen);
        return regel;
    }

    function datumNl(tekst) {
        var delen = String(tekst).split("-");
        if (delen.length !== 3) { return tekst; }
        return delen[2] + "-" + delen[1] + "-" + delen[0];
    }

    function koppelBacklog() {
        $("#backlog-formulier").addEventListener("submit", function (gebeurtenis) {
            gebeurtenis.preventDefault();
            var titel = $("#backlog-titel").value.trim();
            if (!titel) { return; }
            api("/api/backlog", {
                method: "POST",
                json: {
                    titel: titel,
                    omschrijving: $("#backlog-omschrijving").value,
                    prioriteit: $("#backlog-prioriteit").value,
                    deadline: $("#backlog-deadline").value || null
                }
            }).then(function () {
                $("#backlog-formulier").reset();
                toonMelding($("#backlog-melding"), "Taak toegevoegd.", "goed");
                setTimeout(function () { $("#backlog-melding").hidden = true; }, 2500);
                return verversBacklog();
            }).catch(function (fout) {
                toonMelding($("#backlog-melding"), fout.message, "fout");
            });
        });

        alle("#backlog .filterknop[data-status]").forEach(function (knop) {
            knop.addEventListener("click", function () {
                alle("#backlog .filterknop[data-status]").forEach(function (andere) {
                    andere.classList.remove("actief");
                });
                knop.classList.add("actief");
                backlogFilter = knop.dataset.status;
                verversBacklog();
            });
        });

        $("#backlog-opruimen").addEventListener("click", function () {
            if (!window.confirm("Alle afgeronde taken verwijderen?")) { return; }
            api("/api/backlog/opruimen", { method: "POST" })
                .then(function (data) {
                    toonMelding($("#backlog-melding"),
                        data.verwijderd + " taak/taken verwijderd.", "goed");
                    return verversBacklog();
                })
                .catch(function (fout) {
                    toonMelding($("#backlog-melding"), fout.message, "fout");
                });
        });
    }

    /* ===================== Veiligheid ==================================== */

    function verversVeiligheid() {
        return api("/api/veiligheid").then(function (data) {
            tekstIn($("#veiligheid-score"),
                "Controles in orde: " + data.score + " van " + data.score_max);

            var lijst = $("#veiligheid-controles");
            lijst.textContent = "";
            data.controles.forEach(function (controle) {
                var regel = document.createElement("li");

                var icoon = document.createElement("span");
                icoon.className = "controle-icoon " + (controle.ok ? "ok" : "let-op");
                icoon.setAttribute("aria-hidden", "true");
                icoon.textContent = controle.ok ? "✓" : "!";

                var tekstBlok = document.createElement("div");
                var naam = document.createElement("div");
                naam.className = "controle-naam";
                naam.textContent = controle.naam + (controle.ok ? " - in orde" : " - let op");
                var uitleg = document.createElement("div");
                uitleg.className = "controle-uitleg";
                uitleg.textContent = controle.uitleg;
                tekstBlok.appendChild(naam);
                tekstBlok.appendChild(uitleg);

                regel.appendChild(icoon);
                regel.appendChild(tekstBlok);
                lijst.appendChild(regel);
            });

            tekstIn($("#veiligheid-samenvatting"),
                "Afgelopen 24 uur: " + data.gelukt_24u + " keer succesvol ingelogd, " +
                data.mislukt_24u + " mislukte poging(en). Een sessie verloopt na " +
                data.sessie_verloopt_na_minuten + " minuten zonder activiteit.");

            var lichaam = $("#veiligheid-pogingen");
            lichaam.textContent = "";
            if (!data.pogingen.length) {
                var rij = document.createElement("tr");
                var cel = document.createElement("td");
                cel.colSpan = 4;
                cel.textContent = "Nog geen inlogpogingen vastgelegd.";
                rij.appendChild(cel);
                lichaam.appendChild(rij);
                return;
            }
            data.pogingen.forEach(function (poging) {
                var rij = document.createElement("tr");
                [
                    window.grafiekHulp.tijdVolledig(new Date(poging.tijd)),
                    poging.gebruiker || "-",
                    poging.ip
                ].forEach(function (waarde) {
                    var cel = document.createElement("td");
                    cel.textContent = waarde;
                    rij.appendChild(cel);
                });
                var resultaat = document.createElement("td");
                resultaat.className = poging.gelukt ? "resultaat-goed" : "resultaat-fout";
                resultaat.textContent = poging.gelukt ? "✓ gelukt" : "✕ mislukt";
                rij.appendChild(resultaat);
                lichaam.appendChild(rij);
            });
        }).catch(function () { /* stil */ });
    }

    /* ===================== Achtergrond en thema ========================== */

    var achtergrondLaag = $("#achtergrond");
    var sluierLaag = $("#achtergrond-sluier");
    var opslaanTimer = null;

    function slaAchtergrondOp(gegevens, melding) {
        clearTimeout(opslaanTimer);
        opslaanTimer = setTimeout(function () {
            api("/api/achtergrond", { method: "POST", json: gegevens })
                .then(function () {
                    if (melding) {
                        toonMelding($("#achtergrond-melding"), melding, "goed");
                        setTimeout(function () {
                            $("#achtergrond-melding").hidden = true;
                        }, 2000);
                    }
                })
                .catch(function (fout) {
                    toonMelding($("#achtergrond-melding"), fout.message, "fout");
                });
        }, 250);
    }

    function koppelAchtergrond() {
        alle("#preset-raster .preset").forEach(function (knop) {
            knop.addEventListener("click", function () {
                if (knop.disabled) { return; }
                alle("#preset-raster .preset").forEach(function (andere) {
                    andere.classList.remove("actief");
                    andere.setAttribute("aria-pressed", "false");
                });
                knop.classList.add("actief");
                knop.setAttribute("aria-pressed", "true");

                var keuze = knop.dataset.preset;
                achtergrondLaag.style.backgroundImage =
                    getComputedStyle(knop).backgroundImage;
                slaAchtergrondOp(
                    keuze === "afbeelding" ? { type: "afbeelding" } : { preset: keuze },
                    "Achtergrond opgeslagen."
                );
            });
        });

        var verduistering = $("#regelaar-verduistering");
        verduistering.addEventListener("input", function () {
            sluierLaag.style.opacity = String(verduistering.value / 100);
            tekstIn($("#waarde-verduistering"), verduistering.value + "%");
            slaAchtergrondOp({ verduistering: Number(verduistering.value) });
        });

        var vervaging = $("#regelaar-vervaging");
        vervaging.addEventListener("input", function () {
            achtergrondLaag.style.filter = "blur(" + vervaging.value + "px)";
            tekstIn($("#waarde-vervaging"), vervaging.value + "px");
            slaAchtergrondOp({ vervaging: Number(vervaging.value) });
        });

        $("#thema-keuze").addEventListener("change", function (gebeurtenis) {
            var keuze = gebeurtenis.target.value;
            document.documentElement.setAttribute("data-thema", keuze);
            slaAchtergrondOp({ thema: keuze }, "Thema opgeslagen.");
            // De kleuren van de grafieken hangen aan het thema: opnieuw tekenen.
            setTimeout(function () {
                if (laatsteGeschiedenis) { tekenGeschiedenis(laatsteGeschiedenis); }
                if (weerGrafiek) {
                    weerGrafiek.opties.kleur = kleurVan(0);
                    weerGrafiek.teken();
                }
            }, 30);
        });

        var bestandsveld = $("#achtergrond-bestand");
        bestandsveld.addEventListener("change", function () {
            tekstIn($("#achtergrond-bestandsnaam"),
                bestandsveld.files.length ? bestandsveld.files[0].name : "Geen bestand gekozen");
        });

        $("#achtergrond-upload").addEventListener("submit", function (gebeurtenis) {
            gebeurtenis.preventDefault();
            if (!bestandsveld.files.length) {
                toonMelding($("#achtergrond-melding"), "Kies eerst een afbeelding.", "fout");
                return;
            }
            var formulier = new FormData();
            formulier.append("afbeelding", bestandsveld.files[0]);

            fetch("/api/achtergrond/upload", {
                method: "POST",
                headers: { "X-CSRF-Token": CSRF },
                body: formulier,
                credentials: "same-origin"
            }).then(function (antwoord) {
                return antwoord.json().catch(function () { return {}; })
                    .then(function (data) {
                        if (!antwoord.ok) {
                            throw new Error(data.melding ||
                                "Uploaden mislukt (" + antwoord.status + ").");
                        }
                        return data;
                    });
            }).then(function (data) {
                toonMelding($("#achtergrond-melding"), "Achtergrond ingesteld.", "goed");
                achtergrondLaag.style.backgroundImage = "url('" + data.afbeelding_url + "')";
                var eigen = $("#preset-eigen");
                eigen.disabled = false;
                eigen.style.backgroundImage = "url('" + data.afbeelding_url + "')";
                alle("#preset-raster .preset").forEach(function (andere) {
                    andere.classList.remove("actief");
                    andere.setAttribute("aria-pressed", "false");
                });
                eigen.classList.add("actief");
                eigen.setAttribute("aria-pressed", "true");
                $("#achtergrond-verwijderen").hidden = false;
                bestandsveld.value = "";
                tekstIn($("#achtergrond-bestandsnaam"), "Geen bestand gekozen");
            }).catch(function (fout) {
                toonMelding($("#achtergrond-melding"), fout.message, "fout");
            });
        });

        $("#achtergrond-verwijderen").addEventListener("click", function () {
            if (!window.confirm("De eigen achtergrondfoto verwijderen?")) { return; }
            api("/api/achtergrond/afbeelding", { method: "DELETE" }).then(function (data) {
                achtergrondLaag.style.backgroundImage = data.css;
                var eigen = $("#preset-eigen");
                eigen.disabled = true;
                eigen.style.backgroundImage = "";
                eigen.classList.remove("actief");
                $("#achtergrond-verwijderen").hidden = true;
                alle("#preset-raster .preset[data-preset]").forEach(function (knop) {
                    var isHuidige = knop.dataset.preset === data.preset;
                    knop.classList.toggle("actief", isHuidige);
                    knop.setAttribute("aria-pressed", isHuidige ? "true" : "false");
                });
                toonMelding($("#achtergrond-melding"), "Eigen foto verwijderd.", "goed");
            }).catch(function (fout) {
                toonMelding($("#achtergrond-melding"), fout.message, "fout");
            });
        });
    }

    /* ===================== Wachtwoord ==================================== */

    function koppelWachtwoord() {
        $("#wachtwoord-formulier").addEventListener("submit", function (gebeurtenis) {
            gebeurtenis.preventDefault();
            api("/api/wachtwoord", {
                method: "POST",
                json: {
                    huidig: $("#wachtwoord-huidig").value,
                    nieuw: $("#wachtwoord-nieuw").value,
                    herhaling: $("#wachtwoord-herhaling").value
                }
            }).then(function (data) {
                toonMelding($("#wachtwoord-melding"), data.melding, "goed");
                $("#wachtwoord-formulier").reset();
                if (data.opnieuw_inloggen) {
                    setTimeout(function () { window.location.href = "/inloggen"; }, 2500);
                }
            }).catch(function (fout) {
                toonMelding($("#wachtwoord-melding"), fout.message, "fout");
            });
        });
    }

    /* ===================== Opstarten ===================================== */

    function start() {
        maakGrafieken();
        koppelGrafiekknoppen();
        koppelBacklog();
        koppelAchtergrond();
        koppelWachtwoord();

        verversSensoren();
        verversGeschiedenis();
        verversBacklog();
        verversVeiligheid();
        verversWeer(false);

        setInterval(verversSensoren, VERVERS_MS);
        setInterval(verversGeschiedenis, 60000);
        setInterval(verversVeiligheid, 120000);
        if (WEER_AAN) {
            setInterval(function () { verversWeer(false); }, 10 * 60 * 1000);
            var verversKnop = $("#weer-verversen");
            if (verversKnop) {
                verversKnop.addEventListener("click", function () { verversWeer(true); });
            }
        }

        // Volgt het apparaat het systeemthema, dan moeten de grafiekkleuren mee.
        if (window.matchMedia) {
            var voorkeur = window.matchMedia("(prefers-color-scheme: dark)");
            var opWijziging = function () {
                if (document.documentElement.getAttribute("data-thema") !== "auto") { return; }
                if (laatsteGeschiedenis) { tekenGeschiedenis(laatsteGeschiedenis); }
                if (weerGrafiek) {
                    weerGrafiek.opties.kleur = kleurVan(0);
                    weerGrafiek.teken();
                }
            };
            if (voorkeur.addEventListener) {
                voorkeur.addEventListener("change", opWijziging);
            } else if (voorkeur.addListener) {
                voorkeur.addListener(opWijziging);
            }
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
}());
