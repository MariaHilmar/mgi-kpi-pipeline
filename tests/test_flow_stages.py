from flow_stages import flow_map_etapa, parse_status_label


def test_parse_status_label():
    assert parse_status_label("status::Doing") == "Doing"
    assert parse_status_label("tipo::Bug") is None
    assert parse_status_label("status::") is None


def test_flow_map_etapa_gitlab_board():
    assert flow_map_etapa("Backlog") == "Backlog"
    assert flow_map_etapa("Doing") == "Em Desenvolvimento"
    assert flow_map_etapa("Sprint Atual") == "A Fazer"
    assert flow_map_etapa("Em revisão") == "Em Teste"
    assert flow_map_etapa("Delivered", "Aberto") == "Concluído"
    assert flow_map_etapa(None, "Fechado") == "Concluído"
