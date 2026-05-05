import os
from flask import Flask, render_template, redirect, request, url_for, flash
from markupsafe import Markup
from flask_sqlalchemy import SQLAlchemy 
from datetime import datetime
from sqlalchemy import func
import webview
from threading import Thread
import sys
import time

def resource_path(relative_path):
    """ Obtém o caminho absoluto para recursos, funciona em dev e no PyInstaller """
    try:
        # O PyInstaller cria uma pasta temporária e armazena o caminho em _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app = Flask(__name__, 
            template_folder=resource_path('templates'),
            static_folder=resource_path('static'))
app.secret_key = 'aZlB12Tr'

# --- CORREÇÃO DA ORDEM DAS VARIÁVEIS ---

# 1. Primeiro definimos onde o app está rodando
if getattr(sys, 'frozen', False):
    app_path = os.path.dirname(sys.executable)
else:
    app_path = os.path.dirname(os.path.abspath(__file__))

# 2. Agora definimos o caminho do banco e checamos se ele já existe
db_path = os.path.join(app_path, 'fretes.db')
primeira_execucao = not os.path.exists(db_path) # Se não existe, é True

# 3. Configuramos o SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
db = SQLAlchemy(app)

with app.app_context():
    db.create_all()

#  Classe de uso do BD

class RegistroFrete(db.Model):
    __tablename__ = 'Registros_de_Fretes'
    
    id = db.Column('FreteID', db.Integer, primary_key=True, autoincrement=True)
    data_registro = db.Column('DataRG', db.DateTime, default=db.func.current_timestamp())
    
    # Documentação e Identificação
    manifesto_nr = db.Column('ManifestoNR', db.String(12), nullable=False, unique=True)
    placa = db.Column('PlacaMT', db.String(7), nullable=False)
    motorista = db.Column('NomeMT', db.String(100), nullable=False)
    
    # Datas de Operação
    data_carregamento = db.Column('CarregamentoDT', db.Date, nullable=False)
    data_acerto = db.Column('AcertoDT', db.Date, nullable=False)
    
    # Modalidade 1: Frete por KM
    tem_km = db.Column('FreteMT_KM', db.Boolean, default=False, nullable=False)
    km_qtd = db.Column('FreteMT_KM_QTD', db.Integer, default=0, nullable=False)
    km_valor = db.Column('FreteMT_KM_VLR', db.Numeric(10, 2), default=0.00, nullable=False)
    
    # Modalidade 2: Frete Combinado (Valor Fixo)
    tem_combinado = db.Column('FreteMT_COMBINADO', db.Boolean, default=False, nullable=False)
    combinado_valor = db.Column('FreteMT_COMBINADO_VLR', db.Numeric(10, 2), default=0.00, nullable=False)
    
    # Vale Combustível
    tem_combustivel = db.Column('FreteMT_CMB', db.Boolean, default=False, nullable=False)
    combustivel_valor = db.Column('FreteMT_CMB_VLR', db.Numeric(10, 2), default=0.00, nullable=False)

    # Ajudante
    tem_ajudante = db.Column('FreteMT_AJUDANTE', db.Boolean, default=False, nullable=False)
    ajudante_valor = db.Column('FreteMT_AJUDANTE_VLR', db.Numeric(10, 2), default=0.00, nullable=False)

    # Dados de Carga e Faturamento PJ
    frete_pj = db.Column('FretePJ', db.Numeric(10, 2), nullable=False, default=0.00)
    peso = db.Column('Peso', db.Numeric(10, 2), nullable=False, default=0.00)
    volume = db.Column('Volume', db.Integer, nullable=False)

    def __repr__(self):
        return f'<Frete {self.manifesto_nr} - {self.motorista}>'

def run_flask():
    # Roda o servidor Flask sem o modo debug (essencial para executáveis)
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

#  Rota principal
@app.route("/")
def home():
    global primeira_execucao
    if primeira_execucao:
        # Após o primeiro redirecionamento, marcamos como False 
        # para que o usuário possa navegar livremente depois
        primeira_execucao = False 
        return redirect(url_for('registro'))
    
    return redirect(url_for('dashboard'))

@app.route("/dashboard")
def dashboard():
    placa_filtro = request.args.get('placa', '')
    periodo = request.args.get('periodo', 'ano')

    # --- 1. CONSULTA GLOBAL (Para o primeiro card) ---
    # Ignora o filtro de placa, mas respeita o filtro de período (semana/mês/ano)
    query_global = RegistroFrete.query
    
    hoje = datetime.now()
    if periodo == 'semana':
        query_global = query_global.filter(RegistroFrete.data_carregamento >= func.date(hoje, '-7 days'))
    elif periodo == 'mes':
        query_global = query_global.filter(func.strftime('%m', RegistroFrete.data_carregamento) == hoje.strftime('%m'))

    # Soma apenas o faturamento PJ de forma global para o período
    faturamento_global = db.session.query(func.sum(RegistroFrete.frete_pj)).filter(
        RegistroFrete.id.in_([r.id for r in query_global.all()])
    ).scalar() or 0.0

    # --- 2. CONSULTA FILTRADA (Para o resto da página) ---
    query_filtrada = query_global # Começa com o filtro de período já aplicado
    if placa_filtro:
        query_filtrada = query_filtrada.filter(RegistroFrete.placa == placa_filtro)

    registros_filtrados = query_filtrada.all()
    
    # Cálculos baseados APENAS nos registros filtrados (Placa + Período)
    total_pago_motorista = 0.0
    total_recebido_empresa_filtrado = 0.0 # Este é o faturamento da placa específica
    total_peso = 0.0
    total_volume = 0.0
    total_viagens = len(registros_filtrados)

    for reg in registros_filtrados:
        if reg.tem_km:
            valor_frete = float(reg.km_qtd * reg.km_valor)
        else:
            valor_frete = float(reg.combinado_valor)
        
        v_ajudante = float(reg.ajudante_valor) if reg.tem_ajudante else 0.0
        v_combustivel = float(reg.combustivel_valor)
        
        total_pago_motorista += (valor_frete + v_ajudante) - v_combustivel
        total_recebido_empresa_filtrado += float(reg.frete_pj)
        total_peso += float(reg.peso)
        total_volume += float(reg.volume)

    # Cálculos de médias para o resumo
    media_faturamento = total_recebido_empresa_filtrado / total_viagens if total_viagens > 0 else 0
    media_motorista = total_pago_motorista / total_viagens if total_viagens > 0 else 0

    ultimos_registros = query_filtrada.order_by(RegistroFrete.data_registro.desc()).limit(10).all()

    metrics = {
        'faturamento_total_empresa': faturamento_global, # <--- NOVO: Valor fixo da empresa
        'faturamento': total_recebido_empresa_filtrado,  # <--- Valor da placa selecionada
        'frete_motorista': total_pago_motorista,
        'resultado_final': total_recebido_empresa_filtrado - total_pago_motorista,
        'total_viagens': total_viagens,
        'peso': total_peso,
        'volume': total_volume,
        'media_faturamento': total_recebido_empresa_filtrado / total_viagens if total_viagens > 0 else 0,
        'media_motorista': total_pago_motorista / total_viagens if total_viagens > 0 else 0,
        'dados_grafico': [round(total_pago_motorista, 2), round(total_recebido_empresa_filtrado, 2)],
        'ultimos_10': ultimos_registros,
        'placas_disponiveis': [p[0] for p in db.session.query(RegistroFrete.placa).distinct().all()],
        'filtro_ativo': {'placa': placa_filtro, 'periodo': periodo}
    }

    return render_template("dashboard.html", m=metrics)

@app.route("/registro")
def registro():
    return render_template("registro.html")

@app.route("/salvar_frete", methods=['POST'])
def salvar_frete():
    dados_form = request.form
    try:
        data_carreg = datetime.strptime(request.form.get('data_carregamento'), '%Y-%m-%d').date()
        data_acert = datetime.strptime(request.form.get('data_acerto'), '%Y-%m-%d').date()
        peso_bruto = request.form.get('peso') or '0'
        peso_convertido = float(peso_bruto.replace('.', '').replace(',', '.'))
        
        # Criando a instância do modelo com os dados do formulário
        novo_frete = RegistroFrete(
            manifesto_nr=request.form.get('manifesto_nr'),
            placa=request.form.get('placa'),
            motorista=request.form.get('motorista'),
            
            # Use as variáveis convertidas aqui:
            data_carregamento=data_carreg,
            data_acerto=data_acert,
            
            tem_km='tem_km' in request.form,
            km_qtd=int(request.form.get('km_qtd') or 0),
            km_valor=float(request.form.get('km_valor') or 0),
            tem_combinado='tem_combinado' in request.form,
            combinado_valor=float(request.form.get('combinado_valor') or 0),
            tem_combustivel='tem_combustivel' in request.form,
            combustivel_valor=float(request.form.get('combustivel_valor') or 0),
            tem_ajudante='tem_ajudante' in request.form,
            ajudante_valor=float(request.form.get('ajudante_valor') or 0),            
            frete_pj=float(request.form.get('frete_pj') or 0),
            peso=peso_convertido,
            volume=int(request.form.get('volume') or 0)
        )

        # Verifica se já existe uma manifesto com o mesmo número informado
        numero_manifesto = request.form.get('manifesto_nr')
        manifesto_existente = RegistroFrete.query.filter_by(manifesto_nr=numero_manifesto).first()
        if manifesto_existente:
            # Criamos o link para abrir em nova aba usando target="_blank"
            url_edicao = url_for('editar_frete', manifesto_nr=numero_manifesto)
            mensagem = Markup(f'Manifesto {numero_manifesto} já existe. <a href="{url_edicao}" target="_blank" class="alert-link">Clique aqui para abrir e editar em uma nova aba.</a>')
            
            flash(mensagem, 'warning')
            return render_template("registro.html", dados=dados_form)

        # Verifica se tem frete informado (KM ou Combinado) ou se foi marcado os campos de frete mas o campo ficou vazio.
        tem_km = 'tem_km' in request.form
        tem_combinado = 'tem_combinado' in request.form
        km_qtd = request.form.get('km_qtd')
        km_valor = request.form.get('km_valor')
        combinado_valor = request.form.get('combinado_valor')
        if not tem_km and not tem_combinado:
            flash('Erro: Você deve informar ao menos um tipo de frete (KM ou Combinado).', 'danger')
            return render_template("registro.html", dados=dados_form)
        
        if tem_km and (not km_qtd or not km_valor):
            flash('Erro: Você marcou Frete por KM, mas não informou a quantidade e valor.', 'danger')
            return render_template("registro.html", dados=dados_form)
        
        if tem_combinado and not combinado_valor:
            flash('Erro: Você marcou Frete Combinado, mas não informou o valor fixo.', 'danger')
            return render_template("registro.html", dados=dados_form)
        
        db.session.add(novo_frete)
        db.session.commit()
        # Cria a mensagem flutuante
        flash('Registro de frete salvo com sucesso', 'success')
        return redirect(url_for('home'))
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao salvar: {e}', 'danger')
        return render_template("registro.html", dados=request.form)

@app.route("/editar_frete/<manifesto_nr>")
def editar_frete(manifesto_nr):
    # Busca o registro no banco pelo número do manifesto
    registro = RegistroFrete.query.filter_by(manifesto_nr=manifesto_nr).first()
    
    if not registro:
        flash("Registro não encontrado.", "danger")
        return redirect(url_for('home'))
    
    dados_bd = {
        'manifesto_nr': registro.manifesto_nr,
        'placa': registro.placa,
        'motorista': registro.motorista,
        'data_carregamento': registro.data_carregamento.strftime('%Y-%m-%d'),
        'data_acerto': registro.data_acerto.strftime('%Y-%m-%d'),
        'tem_km': registro.tem_km,
        'km_qtd': registro.km_qtd,
        'km_valor': registro.km_valor,
        'tem_combinado': registro.tem_combinado,
        'combinado_valor': registro.combinado_valor,
        'tem_ajudante': registro.tem_ajudante,
        'ajudante_valor': registro.ajudante_valor,
        'tem_combustivel': registro.tem_combustivel,
        'combustivel_valor': registro.combustivel_valor,
        'frete_pj': registro.frete_pj,
        'peso': registro.peso,
        'volume': registro.volume
    }
    
    return render_template("registro.html", dados=dados_bd)

@app.route("/deletar_frete/<manifesto_nr>", methods=['POST'])
def deletar_frete(manifesto_nr):
    registro = RegistroFrete.query.filter_by(manifesto_nr=manifesto_nr).first()
    
    if registro:
        try:
            db.session.delete(registro)
            db.session.commit()
            flash(f"Registro {manifesto_nr} excluído com sucesso!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao excluir: {e}", "danger")
    else:
        flash("Registro não encontrado.", "warning")
        
    return redirect(url_for('consultar_fretes'))

@app.route("/consultar_fretes")
def consultar_fretes():
    # Busca todos os registros ordenados pela data de registro (mais recentes primeiro)
    registros = RegistroFrete.query.order_by(RegistroFrete.data_registro.desc()).all()
    return render_template("consulta.html", registros=registros)


def run_flask():
    # Desativar o reloader é CRUCIAL no executável
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    # 1. Inicia o Flask
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

    # 2. Aguarda 2 segundos para garantir que o Flask subiu antes de abrir a janela
    time.sleep(2)

    # 3. Cria a janela forçando o uso do Microsoft Edge (webview2)
    # Isso evita que o app rode em "background" eterno
    window = webview.create_window(
        'Sistema de Gestão de Fretes', 
        'http://127.0.0.1:5000',
        width=1200, 
        height=800
    )
    
    # O parâmetro gui='cef' ou 'mshtml' pode ser usado se o 'edge' falhar, 
    # mas o padrão moderno é deixar o pywebview escolher ou forçar o edge.
    webview.start(gui='edge')