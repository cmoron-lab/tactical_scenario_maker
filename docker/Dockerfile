# Image du rig e2e — lotusim:jazzy (construite depuis le checkout LOTUSim)
# + node préinstallé pour le backend UI : sa réinstallation à chaque
# recréation de conteneur était un piège récurrent du runbook (docs/rig-e2e.md).
FROM lotusim:jazzy

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
