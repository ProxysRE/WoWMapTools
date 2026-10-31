"""Author the complete DEV2-R4 crypt bestiary and reproducible Builder request.

Original encounter rules, inspired by Warcraft; no copyrighted statblock import.
Every item starts from the project's canonical Builder template.
"""
import copy
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
T=json.loads((ROOT/'foundry_builder/templates.json').read_text())['templates']
SOURCE=ROOT/'requests/builder/sources/void-crypt'
STATS={}
ITEM_ICONS=json.loads((ROOT/'resources/void-crypt-item-icons.json').read_text())


def activation(kind='action',condition=''):
    return dict(type=kind,value=None if kind in ('special','none') else 1,condition=condition)


def targeting(distance=60,count=1,shape=None,size=None,width=None):
    result=dict(range=dict(units='self') if distance=='self' else dict(value=distance,units='ft'),
                affects=dict(type='self' if distance=='self' and not shape else 'creature',count=count,choice=not bool(shape)))
    if shape:
        result['template']=dict(type=shape,size=size,units='ft')
        if width is not None:result['template']['width']=width
        result['prompt']=True
    return result


def uses(maximum=1,recharge=None):
    return dict(max=str(maximum),spent=0,recovery=[dict(period='recharge' if recharge else 'lr',type='recoverAll',formula=str(recharge or ''))])


def feat(key,name,text,kind='utility',act='action',distance=60,count=1,save=None,damage=None,healing=None,
         condition='',shape=None,size=None,width=None,charges=None,status=None,duration=None,passive=False,roll=None):
    row=copy.deepcopy(T['feat']);row['name']=name;row['system']['identifier']=key
    row['system']['source']['rules']='2014';row['system']['type']['value']='monster'
    row['system']['description']['value']='<p>'+html.escape(text)+'</p>'
    if passive:row['mechanics']=dict(passive=True)
    else:
        a=dict(type=kind,activity_name=name,activation=activation(act,condition),targeting=targeting(distance,count,shape,size,width))
        if save:a.update(save=dict(ability=save[0],dc=save[1]),on_save='half' if damage else 'none',damage=[])
        if damage:a['damage']=[dict(formula=f,type=t) for f,t in damage]
        if healing:a['healing']=dict(formula=healing[0],type=healing[1])
        if roll:a['utility']=dict(roll=dict(formula=roll,name=name,visible=False,prompt=False))
        if duration:a['duration']=dict(value=duration,units='round')
        row['mechanics']=dict(activities=[a])
        if charges:row['mechanics']['uses']=charges
        if status:
            row['mechanics']['effects']=[dict(name=name,statuses=[status],transfer=False,activity=0,on_save=False,
                duration=dict(rounds=duration) if duration else {},description=text)]
    return row


def attack(key,name,text,bonus,formula,dtype,reach=5,distance=None,extra=None,magic=False):
    row=copy.deepcopy(T['weapon']);row['name']=name;row['system']['identifier']=key
    row['system']['source']['rules']='2014';row['system']['description']['value']='<p>'+html.escape(text)+'</p>'
    row['system']['type']=dict(value='natural',baseItem='');row['system']['magicalBonus']=0
    row['system']['equipped']=True;row['system']['properties']=[]
    row['system']['damage']['base'].update(number=None,denomination=None,bonus='',types=[dtype],custom=dict(enabled=True,formula=formula))
    row['enhancement_policy']=dict(mode='locked',allowed_groups=[],native_properties=[],material_property=None,reason='Врождённое действие существа; не предмет для крафта.')
    dmg=[dict(formula=formula,type=dtype)]+[dict(formula=f,type=t) for f,t in (extra or [])]
    r=dict(value=distance,units='ft',count=1,target_type='creature') if distance else dict(reach=reach,units='ft',count=1,target_type='creature')
    row['mechanics']=dict(attack=dict(ability='none',bonus=str(bonus),flat=True,type='ranged' if distance else 'melee',classification='spell' if magic else 'weapon'),damage=dmg,range=r,activation=activation())
    return row


def npc(key,name,ac,hp,hp_formula,abilities,cr,kind,size='med',walk=30,climb=0,fly=0,save_profs=(),dr=(),ci=(),languages=(),caster=0,notes='',tactics=''):
    row=copy.deepcopy(T['npc']);row['name']=name;row['items']=[];s=row['system']
    for k,v in zip(('str','dex','con','int','wis','cha'),abilities):s['abilities'][k].update(value=v,proficient=int(k in save_profs),bonuses=dict(check='',save='',skill=''))
    s['attributes']['ac']=dict(calc='flat',flat=ac,formula='')
    s['attributes']['hp']=dict(value=hp,max=hp,temp=0,tempmax=0,formula=hp_formula)
    s['attributes']['movement']=dict(walk=walk,climb=climb,fly=fly,swim=0,burrow=0,units='ft',hover=bool(fly))
    s['attributes']['senses']=dict(ranges=dict(darkvision=60,blindsight=None,tremorsense=None,truesight=None),units='ft',special='')
    s['attributes']['spellcasting']='int' if caster else '';s['attributes']['spell']=dict(level=caster)
    s['spells']={f'spell{i}':dict(value=0,override=0) for i in range(10)};s['spells']['pact']=dict(value=0,override=0)
    s['details'].update(alignment='Хаотично-злой' if kind!='beast' else 'Без мировоззрения',race='Высший эльф' if key=='vaelis' else '',type=dict(value=kind,subtype='Порча Бездны',custom=''),cr=cr,
                        source=dict(book='Крипта Бездны DEV2-R4 — авторский тест для 5 персонажей 6 уровня',page='',license=''))
    s['traits']['size']=size
    for block,value in [('di',[]),('dr',list(dr)),('dv',[]),('ci',list(ci))]:s['traits'][block]=dict(value=value,custom='')
    s['traits']['languages']=dict(value=list(languages),custom='',communication=dict(telepathy=dict(value=60 if kind=='aberration' else None,units='ft')))
    s['skills']={};s['resources']={}
    if key=='vaelis':s['resources']=dict(legact=dict(value=2,max=2),legres=dict(value=2,max=2))
    bio='<h2>'+html.escape(name)+'</h2><p>'+html.escape(notes)+'</p><h3>Тактика</h3><p>'+html.escape(tactics)+'</p>'
    if caster:bio+='<p>Все приведённые силы — особые магические действия без ячеек. Уровень заклинателя указан справочно; список покупных заклинаний отсутствует. Правила прерывания явно приведены в способностях.</p>'
    bio+='<p>Авторский статблок. CR — предварительная оценка, не результат игрового теста. Перемещения, отложенные события, ауры и сложные условия ведёт мастер; кнопки бросков и ресурсы собраны Builder.</p>'
    s['details']['biography']=dict(value=bio,public='')
    n=2 if size=='lg' else 1
    row['prototypeToken'].update(name=name,actorLink=False,width=n,height=n,disposition=-1,displayName=20,displayBars=20,bar1=dict(attribute='attributes.hp'),sight=dict(enabled=False,range=0,visionMode='basic'))
    STATS[key]=row
    return row['items']


def author():
    a=npc('wolf','Сумрачный лесной волк',14,38,'7d8+7',[16,15,12,3,12,6],1,'beast',walk=40,
          notes='Чёрный лесной волк с холодным свечением глаз. Под шерстью пульсируют тёмные жилы.',tactics='Сначала помечает крайнего противника. Два волка обходят, остальные удерживают фронт. Не прыгает сквозь стены. Раненая стая может отступить.')
    a.extend([
        attack('wolf-bite','Укус','Действие: +5, 5 фт., одна цель; 1d8+3 колющего урона.',5,'1d8+3','piercing'),
        feat('wolf-scent','Запах страха','Бонусное действие, одна видимая цель в 30 фт. До конца следующего хода волка его первое попадание укусом по этой цели наносит ещё 1d4 психического урона. Только одна метка этого волка; метки других волков не усиливают его удар. Метка видима как тёмный след. Условие отслеживается вручную.',act='bonus',distance=30),
        feat('wolf-mark-damage','Отзвук метки','Вспомогательный урон 1d4 психического; только после первого попадания владельца по цели его действующей метки. После броска метку снять. Не прибавлять к каждому укусу.',kind='damage',act='special',condition='Первое попадание укусом по собственной метке',distance=5,damage=[('1d4','psychic')]),
        feat('wolf-rush','Рывок из сумрака','Действие, перезарядка 5–6 в начале хода. Волк перемещается до 20 фт. по свободному пути (провоцирует обычные атаки) и выполняет один укус отдельной кнопкой. Если перед укусом прошёл по прямой 15 фт. и попал, цель Большого или меньшего размера проходит спасбросок Силы Сл 13 отдельной кнопкой; провал — сбита с ног, успех — без эффекта. Прыжок и проверку пути ведёт мастер.',distance=20,charges=uses(recharge=5)),
        feat('wolf-trip','Сбить с ног','Вспомогательная кнопка: после попадания Рывком при выполненных условиях; одна цель Большого или меньшего размера в 5 фт., Сила Сл 13. Провал — сбита с ног; успех — без эффекта. Встаёт обычным способом. Не расходует второе действие.',kind='save',act='special',condition='Попадание Рывком после 15 фт. прямого разбега',distance=5,save=('str',13),status='prone'),
        feat('wolf-pack','Стая смыкается','Реакция: другой волк в 10 фт. получил урон. Владелец перемещается до 10 фт. к нападающему, которого видит в 40 фт.; обычные провоцированные атаки действуют. Не даёт бесплатной атаки. Перемещение вручную.',act='reaction',condition='Другой волк в 10 фт. получил урон',distance=40)])

    a=npc('spider','Паук чернильной паутины',14,45,'6d10+12',[12,16,14,3,10,6],2,'beast',size='lg',climb=30,
          notes='Крупный паук, оставляющий липкую чёрную паутину.',tactics='Опутывает дальнюю цель, затем кусает ближайшего врага. Кладку размещает один раз; не одновременно с выстрелом паутины, поскольку оба требуют действия.')
    a.extend([
        attack('spider-bite','Ядовитый укус','Действие: +5, 5 фт., одна цель; 1d8+3 колющего и 1d6 яда. Не накладывает состояние «отравлен».',5,'1d8+3','piercing',extra=[('1d6','poison')]),
        feat('spider-web','Чернильная паутина','Действие, перезарядка 5–6 в начале хода; одна видимая цель Большого или меньшего размера в 30 фт. Ловкость Сл 13: провал — опутана до освобождения, успех — без эффекта. Цель или соседний союзник действием проходит Силу (Атлетика) Сл 13 либо разрушает паутину (КД 10, 10 хитов; иммунитет к яду и психическому урону). Повторное попадание не складывается. Освобождение и снятие эффекта вручную.',kind='save',distance=30,save=('dex',13),status='restrained',charges=uses(recharge=5)),
        feat('spider-cocoon','Кокон шёпота','Пассивно: только существо, опутанное паутиной этого паука, получает помеху проверкам Мудрости (Внимательность). Не мешает спасброскам и не лишает хода. Эффект заканчивается вместе с паутиной; условие вручную.',passive=True),
        feat('spider-brood','Тёмный выводок','Действие, 1/долгий отдых: размещает видимую кладку на свободной поверхности в 15 фт. (КД 10, 10 хитов). В начале следующего хода паука неповреждённая кладка выпускает двух паучат в свободные соседние клетки, затем исчезает. Уничтоженная кладка никого не выпускает. Паучата впервые действуют только после своего полного круга инициативы; одновременно не более двух от одной кладки. Призыв и инициативу ведёт мастер.',distance=15,charges=uses())])

    a=npc('bear','Изломанный чащобный медведь',14,110,'13d10+39',[18,10,16,3,12,6],4,'beast',size='lg',walk=35,save_profs=('str','con'),
          notes='Чёрный медведь, чьи рёв и дыхание отзываются чужим голосом.',tactics='Чередует две лапы и тяжёлый замах. Рёв один раз, если его окружили. Сметающий замах всегда оставляет окно для ответа.')
    a.extend([
        attack('bear-paw','Лапа','Действие: +6, 5 фт., одна цель; 2d6+4 рубящего урона.',6,'2d6+4','slashing'),
        feat('bear-multi','Мультиатака','Действие: две атаки Лапой, каждая отдельной кнопкой. Заменяет обычное действие, не добавляет третью атаку.',distance=5),
        feat('bear-sweep','Сметающий замах','Действие, перезарядка 5–6. Все другие существа в конусе 10 фт.: Ловкость Сл 14, 3d6 дробящего урона, половина при успехе; при провале цель Большого или меньшего размера также отталкивается на 5 фт. До начала следующего хода медведя атаки по нему имеют преимущество. Отталкивание и преимущество вручную.',kind='save',distance='self',count='',shape='cone',size=10,save=('dex',14),damage=[('3d6','bludgeoning')],charges=uses(recharge=5)),
        feat('bear-roar','Чужой рёв','Действие, 1/долгий отдых; до двух видимых врагов в 20 фт., слышащих рёв. Мудрость Сл 14: провал — испуганы медведем до конца следующего хода медведя, успех — без эффекта. Повторного спасброска нет; мастер снимает состояние в указанный момент.',kind='save',distance=20,count=2,save=('wis',14),status='frightened',duration=1,charges=uses()),
        feat('bear-pain','Боль сквозь шкуру','Реакция, 1/долгий отдых: после одного источника урона не менее 15 владелец получает 12 временных хитов. Они действуют 1 минуту, не складываются с другими временными хитами. До конца следующего хода медведя атаки по нему имеют преимущество; это условие ведёт мастер.',kind='heal',act='reaction',condition='Получено не менее 15 урона одним источником',distance='self',healing=('12','temphp'),charges=uses())])

    a=npc('acolyte','Аколит Последней Истины',13,44,'8d8+8',[9,12,12,16,14,12],2,'humanoid',languages=('common',),caster=5,notes='Ученик Ваэлиса, добровольно принявший его учение.',tactics='Сначала защищает союзника или поддерживает разлом, затем стреляет. Не поддерживает ритуал сквозь стены. Бежит, когда погибают защитники.')
    a.extend([
        attack('acolyte-bolt','Стрела Тьмы','Действие: дальняя магическая атака +5, 60 фт., одна видимая цель; 2d8+3 некротического урона.',5,'2d8+3','necrotic',distance=60,magic=True),
        feat('acolyte-flesh','Заёмная плоть','Действие, 2/долгий отдых; одно видимое существо Бездны или последователь Ваэлиса в 30 фт. получает 2d6+3 временных хитов на 1 минуту. Не лечит настоящие хиты и не складывается с временными хитами.',kind='heal',distance=30,healing=('2d6+3','temphp'),charges=uses(2)),
        feat('acolyte-revelation','Болезненное откровение','Действие, 1/долгий отдых; одна видимая цель в 60 фт. Мудрость Сл 13: провал — 2d6 психического урона и до конца следующего хода аколита не может совершать реакции; успех — половина урона без ограничения. Снятие ограничения реакций вручную.',kind='save',save=('wis',13),damage=[('2d6','psychic')],charges=uses()),
        feat('acolyte-channel','Питать разлом','Действие; одно видимое порождение в 30 фт. До начала следующего хода аколита первое попадание выбранного союзника наносит ещё 1d6 силового урона. Требует концентрации как на заклинании: урон вызывает обычную проверку Телосложения, потеря сознания или новая концентрация прекращают ритуал. Бонус не складывается; мастер отслеживает концентрацию и первое попадание.',distance=30),
        feat('acolyte-channel-damage','Дар разлома — урон','Вспомогательно после первого попадания усиленного союзника: 1d6 силового урона той же цели. Только при действующем Питать разлом; после этого усиление заканчивается.',kind='damage',act='special',condition='Первое попадание усиленного союзника при действующей концентрации',damage=[('1d6','force')])])

    a=npc('caster','Сумеречный заклинатель',14,66,'12d8+12',[9,14,12,18,12,13],3,'humanoid',save_profs=('int','wis'),languages=('common',),caster=7,notes='Последователь, превращающий формулы магистра в разломы пространства.',tactics='Начинает с колодца или подготовки линии. Не имеет бесплатного дополнительного залпа при завершении подготовленного удара.')
    a.extend([
        attack('caster-bolt','Теневой снаряд','Действие: дальняя магическая атака +6, 90 фт., одна видимая цель; 2d8+4 некротического урона.',6,'2d8+4','necrotic',distance=90,magic=True),
        feat('caster-well','Колодец притяжения — подготовка','Действие, перезарядка 5–6: отметить видимую точку на полу в 60 фт. и круг радиусом 10 фт. В начале следующего хода заклинатель тратит действие на разрешение отдельной кнопкой. До разрешения требует концентрации; при её потере круг исчезает. Все участники получают полный ход для выхода. Не наносит урон при размещении.',distance=60,charges=uses(recharge=5)),
        feat('caster-well-resolve','Колодец — разрешение','Действие, только если колодец подготовлен предыдущим ходом и концентрация сохранена. Все существа в отмеченном круге: Сила Сл 14, провал — 2d6 силового урона и притягивание к центру до 10 фт.; успех — половина без перемещения. Круг исчезает. Шаблон поставить в прежнюю точку; перемещение вручную.',kind='save',distance=60,count='',shape='radius',size=10,save=('str',14),damage=[('2d6','force')]),
        feat('caster-line','Рассекающий сумрак — подготовка','Действие, перезарядка 5–6: обозначить линию длиной 40, шириной 5 фт. от текущего места. В начале следующего хода разрешить отдельным действием. Линия не поворачивается и не перемещается вслед за целью; требует концентрации до разрешения. При потере концентрации отменяется.',distance='self',charges=uses(recharge=5)),
        feat('caster-line-resolve','Рассекающий сумрак — удар','Действие, только для подготовленной неизменной линии 40×5 фт.; все существа внутри: Ловкость Сл 14, 3d8 некротического урона, половина при успехе. Не сочетается с обычным снарядом в том же действии.',kind='save',distance='self',count='',shape='line',size=40,width=5,save=('dex',14),damage=[('3d8','necrotic')]),
        feat('caster-fade','Угасание','Бонусное действие, 1/долгий отдых: телепортируется в свободное видимое место в 15 фт. Не проходит через закрытую дверь без видимости и не создаёт невидимость. Телепортация вручную.',act='bonus',distance=15,charges=uses())])

    a=npc('voidguard','Страж разлома',15,85,'10d10+30',[18,10,16,6,12,10],3,'aberration',size='lg',save_profs=('str','con'),ci=('poisoned',),notes='Массивное синее порождение с бронированными наплечниками.',tactics='Стоит рядом с аколитом. Хваткой возвращает приблизившегося противника. После смерти сохраняет инициативу до распада ядра.')
    a.extend([
        attack('guard-fist','Удар пустоты','Действие: +6, 5 фт., одна цель; 1d8+4 силового урона.',6,'1d8+4','force',magic=True),
        feat('guard-multi','Мультиатака','Действие: два Удара пустоты отдельными кнопками. Хватка заменяет обе атаки, а не добавляется к ним.',distance=5),
        feat('guard-grip','Хватка пустоты','Действие, перезарядка 5–6; одна видимая цель Большого или меньшего размера в 30 фт. Сила Сл 14: провал — 2d6 силового урона и притягивание до 15 фт. к стражу; успех — половина без перемещения. Не протаскивает сквозь стены. Перемещение вручную.',kind='save',distance=30,save=('str',14),damage=[('2d6','force')],charges=uses(recharge=5)),
        feat('guard-protect','Принять страдание','Реакция: видимый союзник в 5 фт. получает урон от атаки. Уменьшить этот урон на 8 (не ниже нуля); страж теряет столько настоящих хитов, сколько урона предотвратил. Потеря не уменьшается сопротивлениями, не перенаправляется повторно. Это не лечение и не бросок урона; оба изменения хитов вручную.',act='reaction',condition='Союзник в 5 фт. получил урон от атаки',distance=5),
        feat('guard-collapse','Нестабильный распад','Вспомогательно: после гибели отметить ядро в месте стража. Оно остаётся до начала его следующего хода инициативы, затем все существа в 10 фт. проходят Ловкость Сл 13: 2d6 силового урона, половина при успехе. Ядро можно заранее уничтожить действием без проверки в соседстве либо атакой (КД 12, 5 хитов). Уничтоженное ядро не взрывается. До указанного срока не бросать урон; мёртвого стража не удалять из инициативы.',kind='save',act='special',condition='Начало следующего хода после гибели; ядро не уничтожено',distance='self',count='',shape='radius',size=10,save=('dex',13),damage=[('2d6','force')])])

    a=npc('stalker','Пожиратель эха',15,52,'8d8+16',[12,16,14,8,13,10],2,'aberration',walk=35,notes='Тёмный силуэт с фиолетовой пустотой вместо лица.',tactics='Охотится за одиночками, но не телепортируется из любой точки карты. Голос крадёт только один раз; остальное время использует когти.')
    a.extend([
        attack('stalker-claw','Коготь тени','Действие: +5, 5 фт., одна цель; 1d6+3 рубящего урона.',5,'1d6+3','slashing'),
        feat('stalker-multi','Мультиатака','Действие: две атаки Когтем тени, бросать отдельно.',distance=5),
        feat('stalker-step','Шаг за спину','Бонусное действие, перезарядка 5–6: из тусклого света или темноты телепортируется до 20 фт. в свободное видимое место с тусклым светом или темнотой. Не даёт невидимость, преимущество на атаку или дополнительное действие. Условия освещения и перенос вручную.',act='bonus',distance=20,charges=uses(recharge=5)),
        feat('stalker-voice','Украденный голос','Действие, 1/долгий отдых; одна видимая цель в 30 фт. Телосложение Сл 13: провал — 2d6 психического урона и цель не может говорить или использовать словесные компоненты до конца следующего хода пожирателя; успех — половина урона без немоты. Не запрещает бессловесные действия. Окончание и ограничение компонентов вручную.',kind='save',distance=30,save=('con',13),damage=[('2d6','psychic')],charges=uses()),
        feat('stalker-hunger','Голод по одиночеству','Вспомогательный урон: один раз в собственный ход после попадания Когтем по цели, у которой нет дееспособного союзника в 5 фт., дополнительно 2d6 психического урона. Не срабатывает на второй коготь того же хода. Условие проверяет мастер.',kind='damage',act='special',condition='Первое подходящее попадание в свой ход по изолированной цели',distance=5,damage=[('2d6','psychic')])])

    a=npc('faceless','Безликий смотритель',15,135,'18d10+36',[18,10,14,12,16,14],5,'aberration',size='lg',save_profs=('con','wis'),ci=('frightened',),notes='Древний безликий, надзирающий за подготовкой ритуала.',tactics='Один элитный противник перед финалом. Его два отголоска выходят с задержкой; в бой не добавлять ещё аколитов сверх указанной расстановки.')
    a.extend([
        attack('faceless-slam','Размашистый удар','Действие: +7, досягаемость 10 фт., одна цель; 2d6+4 дробящего урона.',7,'2d6+4','bludgeoning',reach=10),
        feat('faceless-multi','Мультиатака','Действие: два Размашистых удара отдельными кнопками.',distance=10),
        feat('faceless-gaze','Тяжесть взгляда — подготовка','Действие, перезарядка 5–6: обозначить конус 20 фт. из текущей точки. До начала следующего хода направление неизменно; затем требуется отдельное действие для разрешения. Если смотритель недееспособен, подготовка отменяется. До разрешения урона нет.',distance='self',charges=uses(recharge=5)),
        feat('faceless-gaze-hit','Тяжесть взгляда — удар','Действие, только для подготовленного конуса 20 фт.; все враги внутри: Мудрость Сл 15, 3d6 психического урона, половина при успехе. При провале скорость уменьшается на 10 фт. до конца следующего хода смотрителя; уменьшение не складывается, отслеживается вручную.',kind='save',distance='self',count='',shape='cone',size=20,save=('wis',15),damage=[('3d6','psychic')]),
        feat('faceless-kneel','Приказ преклониться','Действие, 1/долгий отдых; до трёх видимых врагов Большого или меньшего размера в 30 фт. Сила Сл 15: провал — сбиты с ног, успех — без эффекта. Встают обычным способом.',kind='save',distance=30,count=3,save=('str',15),status='prone',charges=uses()),
        feat('faceless-call','Позвать отголоски','Действие, 1/долгий отдых: обозначает два свободных места в 20 фт. В начале следующего хода появляются два Отголоска разлома. Призыв отменяется, если смотритель погиб или стал недееспособен. Отголоски впервые действуют только в следующем круге инициативы. Не более двух призванных им существ. Места, призыв и инициативу ведёт мастер.',distance=20,charges=uses())])

    a=npc('echo','Отголосок разлома',12,18,'4d6+4',[8,14,12,5,10,6],0.5,'aberration',size='sm',walk=25,fly=25,notes='Малое синее порождение для волн босса и смотрителя.',tactics='Слабое подкрепление. Не получает немедленную атаку при появлении.')
    a.extend([
        attack('echo-touch','Касание разлома','Действие: +4, 5 фт., одна цель; 1d6+2 силового урона.',4,'1d6+2','force',magic=True),
        feat('echo-flicker','Мерцание','Бонусное действие, 1/долгий отдых: Отход. До конца текущего хода обычное движение отголоска не провоцирует атак. Срок вручную.',act='bonus',distance='self',charges=uses()),
        feat('echo-pop','Затухающий всплеск','После гибели оставляет заметную искру. В начале следующего хода его инициативы искра исчезает: существа в 5 фт. проходят Ловкость Сл 12, 1d6 силового урона, половина при успехе. Искру можно погасить действием из соседней клетки, без проверки. Отложенное событие ведёт мастер; не взрывать сразу при смерти.',kind='save',act='special',condition='Следующий ход после гибели; искра не погашена',distance='self',count='',shape='radius',size=5,save=('dex',12),damage=[('1d6','force')])])

    a=npc('spiderling','Паучонок чернильного выводка',12,7,'2d4+2',[6,13,12,1,8,3],0.125,'beast',size='sm',walk=25,climb=25,notes='Малое подкрепление из кладки; максимум два от одной кладки.',tactics='Нападает на ближайшую доступную цель. Появление не даёт немедленного хода.')
    a.extend([attack('spiderling-bite','Малый укус','Действие: +3, 5 фт., одна цель; 1d4+1 колющего урона.',3,'1d4+1','piercing'),
              feat('spiderling-cling','Цепляющиеся лапки','Пассивно: если два живых паучонка находятся в 5 фт. от одного врага, его скорость уменьшается на 5 фт. Пока условие соблюдается; не складывается с другими такими парами. Условие и скорость вручную.',passive=True)])

    a=npc('vaelis','Магистр Ваэлис — Постигший Истину',16,300,'40d8+120',[10,14,16,18,14,18],8,'humanoid',save_profs=('con','int','wis'),languages=('common','elvish'),caster=11,
          notes='Высший эльф, исследовавший память человеческой крипты. Уверен, что подчинил Бездну. Фаза I выше 150 хитов; фаза II при 150 или меньше, один раз, без лечения и без потери нанесённого сверх порога урона.',
          tactics='Два легендарных действия за раунд, восстанавливаются в начале своего хода; не более одного разряда за раунд. При первом тесте бой на полных ресурсах группы. Ходы с подготовкой и разрешением крупных атак не содержат обычной мультиатаки. Подробный сценарий и помощник мастера входят в комплект.')
    a.extend([
        attack('vaelis-ray','Исправление ошибки — фаза I','Действие фазы I: дальняя магическая атака +7, 90 фт., одна видимая цель; 2d8+4 силового урона. В фазе II использовать отдельную психическую версию.',7,'2d8+4','force',distance=90,magic=True),
        attack('vaelis-ray-void','Исправление ошибки — фаза II','Действие фазы II: дальняя магическая атака +7, 90 фт., одна видимая цель; 2d8+4 психического урона. Заменяет силовую версию, не добавляется к ней.',7,'2d8+4','psychic',distance=90,magic=True),
        feat('vaelis-multi','Мультиатака: Исправление ошибки','Действие: два снаряда Исправления ошибки своей фазы, бросать отдельно; разрешено выбрать разные цели. Не используется при подготовке, призыве или разрешении крупной способности.',distance=90,count=2),
        feat('vaelis-line','Линия доказательства — подготовка','Действие фазы I, перезарядка 5–6: обозначить линию 60×5 фт. из текущего места. Точка начала и направление неизменны. В начале следующего хода разрешить отдельным действием. Считать подготовку заклинанием 3 круга для контрзаклинания; оно отменяет подготовку. Сл разрушения подготовленной руны Рассеиванием магии — 15. Недееспособность также отменяет удар. Урон при подготовке не наносится.',distance='self',charges=uses(recharge=5)),
        feat('vaelis-line-hit','Линия доказательства — удар','Действие, только при действующей подготовке с прошлого хода. Все существа в прежней линии 60×5 фт. проходят Ловкость Сл 15: 4d8 силового урона, половина при успехе. Завершение тратит действие; дополнительной мультиатаки нет. Отменённая подготовка не разрешается.',kind='save',distance='self',count='',shape='line',size=60,width=5,save=('dex',15),damage=[('4d8','force')]),
        feat('vaelis-mirrors','Безупречное отражение','Действие фазы I, 1/долгий отдых: две копии рядом с магом на 1 минуту. Копии не имеют ходов и не блокируют клетки. При первом попадании атакой по Ваэлису в раунде, пока есть копии, он может реакцией уничтожить одну копию и отменить только это попадание. Площадной эффект, затронувший Ваэлиса, уничтожает обе копии, но действует на самого мага как обычно. Истинное зрение обходит подмену. Количество копий и реакция вручную.',distance='self',charges=uses()),
        feat('vaelis-detonation','Резонансная детонация — подготовка','Действие любой фазы, перезарядка 5–6: Ваэлис начинает видимое накопление энергии. Его положение фиксируется до разрешения; не перемещается и не использует легендарные действия. В начале следующего хода он тратит действие на выпуск. Подготовка считается заклинанием 3 круга: контрзаклинание отменяет её; рассеивание руны Сл 15 или недееспособность также отменяют. Укрытие за каменной колонной/сплошной стеной полностью защищает. Мастер заранее показывает область и укрытия; не добавляет новых опасных секторов во время подготовки.',distance='self',charges=uses(recharge=5)),
        feat('vaelis-detonation-hit','Детонация — выпуск','Действие, только после полной подготовки с прошлого хода. Все существа в радиусе 60 фт. без полного каменного укрытия: Ловкость Сл 15, 4d8 силового урона, половина при успехе. В фазе II вместо силового 5d8 психического отдельной кнопкой ниже. Сам Ваэлис не цель. Отсечение закрытых колоннами целей вручную; удар не проходит сквозь стены.',kind='save',distance='self',count='',shape='radius',size=60,save=('dex',15),damage=[('4d8','force')]),
        feat('vaelis-voice-hit','Голос из-за звёзд — выпуск','Действие фазы II, вместо обычного выпуска подготовленной детонации. Радиус 60 фт., все другие существа без полного каменного укрытия: Ловкость Сл 15, 5d8 психического урона, половина при успехе. Не бросать одновременно с обычной детонацией. Положение фиксируется на время подготовки; новые секторы не размещаются.',kind='save',distance='self',count='',shape='radius',size=60,save=('dex',15),damage=[('5d8','psychic')]),
        feat('vaelis-phase','Фаза II: Вас нужно исправить','Пассивный переход один раз при 150 или меньше хитов, если Ваэлис жив. Отменяет незаконченную подготовку фазы I; не лечит, не обнуляет эффекты и ресурсы, не даёт внеочередного действия. Срабатывает визуально сразу, новые действия доступны на его обычном ходу. Эльф остаётся Средним; огромный силуэт — только аура. Включить фазу помощником мастера либо отметить вручную.',passive=True),
        feat('vaelis-wave','Незваные свидетели — подготовка волны','Действие фазы II, всего две волны за бой. Волна I: два отголоска. Волна II: один Страж разлома и один отголосок. Между подготовками волн не менее двух раундов. Два разлома появляются на заранее отмеченных свободных местах; через полный круг инициативы в начале следующего хода Ваэлиса требуется действие для выпуска. Пока разлом открыт, его можно атаковать (КД 13, 12 хитов, иммунитет к яду и психическому) либо закрыть действием из соседней клетки: Интеллект (Магия) Сл 14. Закрытый разлом не выпускает своё существо. Максимум три живых призванных существа; лимит и места проверяет помощник. Новые существа не атакуют при появлении; первый ход — в следующем круге инициативы после босса. Призыв прекращается при смерти босса. Помощник ведёт разломы и лимит; мастер запускает действия, не дублируя расход кнопки и помощника.',distance=60,charges=uses(2)),
        feat('vaelis-sector','Переписать пространство — подготовка','Действие фазы II, перезарядка 5–6: обозначить конус 30 фт. из выбранной неподвижной точки арены. Он становится опасным в начале следующего хода Ваэлиса и существует до начала следующего после этого хода. Подготовку и границы объявить всем. Одновременно один сектор; предыдущий исчезает при новом. Не применять в раунд подготовки или выпуска детонации. Мастер выбирает сектор, из которого каждый затронутый персонаж способен выйти обычным перемещением или Рывком; не закрывать единственный выход.',distance='self',charges=uses(recharge=5)),
        feat('vaelis-sector-tick','Разрыв пространства — урон сектора','Вспомогательно, только для действующего сектора: существо, впервые вошедшее в него за ход или начавшее там ход, проходит Ловкость Сл 15; 3d6 силового урона, половина при успехе. Не чаще одного раза за ход одного существа, не при начальном появлении сектора под ним. Шаблон конуса 30 фт. разместить в прежней точке; границы и сроки вручную.',kind='save',act='special',condition='Первый вход за ход или начало хода в действующем секторе',distance='self',count='',shape='cone',size=30,save=('dex',15),damage=[('3d6','force')]),
        feat('vaelis-bond','Парадокс близости — метки','Действие фазы II, 1/долгий отдых: два видимых разных врага в 60 фт., находящихся не далее 30 фт. друг от друга. Метки видимы. Если до начала следующего хода Ваэлиса они окажутся в 5 фт. друг от друга, обе метки гаснут без последствий. Иначе каждый проходит Мудрость Сл 15 отдельной кнопкой: 3d6 психического урона, половина при успехе; затем метки исчезают. Если одна цель теряет сознание до срока, обе метки гаснут. Не накладывать во время подготовки детонации. Дистанции и сроки вручную.',distance=60,count=2,charges=uses()),
        feat('vaelis-bond-hit','Парадокс — разрыв связи','Вспомогательно в начале следующего хода босса, только для двух непогашенных меток; каждый Мудрость Сл 15, 3d6 психического урона, половина при успехе. Если метки погашены или одна цель без сознания, кнопку не использовать. После разрешения снять обе метки.',kind='save',act='special',condition='Срок двух непогашенных меток наступил',distance=60,count=2,save=('wis',15),damage=[('3d6','psychic')]),
        feat('vaelis-legend-move','Легендарное действие: Сместить аксиому','После окончания чужого хода, стоимость 1 из 2 легендарных действий: Ваэлис перемещается до 10 фт. без провоцирования атак. Не более одного такого перемещения за раунд; не во время подготовки детонации. Восстанавливает запас в начале своего хода. Перемещение и ограничение частоты вручную.',act='legendary',distance='self'),
        feat('vaelis-legend-ray','Легендарное действие: Отзвук мысли','После окончания чужого хода, стоимость 1 из 2 легендарных действий, не более одного разряда за раунд; одна видимая цель в 60 фт. Ловкость Сл 15: 1d8+4 психического урона, половина при успехе. Недоступно во время подготовки детонации. Запас восстанавливается в начале своего хода; частоту ведёт мастер.',kind='save',act='legendary',distance=60,save=('dex',15),damage=[('1d8+4','psychic')]),
        feat('vaelis-resistance','Легендарная устойчивость (2/день)','Вспомогательно после провала собственного спасброска: заменить провал успехом, расходуя одно из двух использований ресурса legres. Восстановление после долгого отдыха. Выбор мастера, не автоматическое срабатывание.',act='special',condition='Провален собственный спасбросок',distance='self')])
    a=npc('rift','Нестабильный разлом — цель ритуала',13,12,'2d8+3',[1,1,1,1,1,1],0,'construct',size='med',walk=0,
          ci=('charmed','frightened','poisoned','prone','restrained','stunned','unconscious'),
          notes='Технический Actor для видимой разрушаемой руны. Не существо-подкрепление, не получает ходов и не приносит XP.',
          tactics='Уничтожение до 0 хитов закрывает разлом. Успешная Магия Сл 14 действием из соседней клетки также закрывает его; мастер отмечает успех в помощнике.')
    STATS['rift']['system']['traits']['di']['value']=['poison','psychic']
    a.append(feat('rift-rule','Закрыть разлом','Неподвижная цель: КД 13, 12 хитов, иммунитет к яду и психическому урону. Не имеет действий, реакций или инициативы. При 0 хитов закрыт; либо персонаж действием из соседней клетки делает Интеллект (Магия) Сл 14. После успешной проверки мастер отмечает закрытие в помощнике. Рассеивание магии (эффект 3 круга) также закрывает разлом. Прочие состояния и принудительные перемещения к руне не применяются. Шаблон на полу проходим, не является стеной.',passive=True))
    identifiers={i['system']['identifier'] for a in STATS.values() for i in a['items']}
    if identifiers!=set(ITEM_ICONS):raise ValueError('Crypt item icon coverage differs from authored abilities')
    return STATS


APPEARANCES={
    'wolf':dict(display_id=73),'spider':dict(display_id=30),'bear':dict(display_id=706),
    'acolyte':dict(character=dict(race='human',gender='male'),equipment=dict(chest=14136,boots=43,main_hand=35),pose='idle'),
    'caster':dict(character=dict(race='human',gender='female'),equipment=dict(chest=14152,boots=43,main_hand=35),pose=dict(animation_id=51,fraction=.5)),
    'voidguard':dict(display_id=1130),'stalker':dict(display_id=18050),'faceless':dict(display_id=27408),
    'echo':dict(display_id=18069),'spiderling':dict(display_id=30),
    # Original high-elf mage display is ghosted (128). This living boss uses an
    # explicit opaque display override, recorded in token provenance.
    'vaelis':dict(display_id=17305,display_alpha=255,pose='idle')}


# Selected against actual rendered candidates, not one frontal default for all.
PORTRAIT_ANGLES=dict(wolf=40,spider=30,bear=35,acolyte=25,caster=-25,voidguard=25,stalker=30,faceless=25,echo=-30,spiderling=30,vaelis=25)
# Canonical map facing; artistic portrait angles must never rotate token pixels.
TOKEN_ANGLES={key:-90 for key in APPEARANCES}


def placements():
    out=[]
    def group(enc,scene,actor,points):
        for i,xy in enumerate(points):
            row=STATS[actor];n=row['prototypeToken']['width']
            out.append(dict(id=f'{enc}-{actor}-{i+1}',actor=actor,scene='crypt-'+scene,position=xy,width=n,height=n,
                            actor_link=False,disposition='hostile',hidden=False))
    group('e1','entrance','wolf',[[16.5,5.5],[19.5,6.5],[23.5,5.5],[22.5,9]])
    group('e2','entrance','spider',[[5.5,17.5],[8.5,20.5],[6,24]])
    group('e3-optional','entrance','bear',[[33,22]])
    group('e3-optional','entrance','wolf',[[31.5,17.5],[35.5,20.5]])
    group('g1','passages','voidguard',[[15.5,14.5]])
    group('g1','passages','acolyte',[[14,12.8],[17,15.8]])
    group('g2','passages','caster',[[23.5,29]])
    group('g2','passages','stalker',[[22,30.5],[24.8,28]])
    group('g3','passages','voidguard',[[45.5,21]])
    group('g3','passages','acolyte',[[43.8,22.5]])
    group('g4','passages','faceless',[[67.5,20]])
    group('g5-optional','passages','caster',[[49.5,10.5]])
    group('g5-optional','passages','acolyte',[[48.2,11.5]])
    group('g6-optional','passages','stalker',[[68.5,35]])
    group('g6-optional','passages','acolyte',[[67.2,36.5]])
    group('boss','sanctum','vaelis',[[21,18]])
    return fit_placements(out)


def fit_placements(rows):
    """Keep token footprints off actual walls, props, arrival zones and peers."""
    import sys,math
    sys.path.insert(0,str(ROOT))
    from wowmap.foundry import compile_scene
    from wowmap.navigation import walk_mask,find_path
    keys=('crypt-entrance','crypt-passages','crypt-sanctum')
    plans={k:json.loads((ROOT/'examples'/('void-'+k+'.json')).read_text()) for k in keys}
    regions={k:{r['id'] for r in p['foundry']['regions']} for k,p in plans.items()}
    masks={};occupied={k:[] for k in keys};starts={'crypt-entrance':(20,4),'crypt-passages':(5.5,20.5),'crypt-sanctum':(7,18)}
    def overlap(a,b):return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]
    for row in rows:
        key=row['scene'];n=row['width'];p=plans[key]
        if (key,n) not in masks:
            scene=compile_scene(p,'nav',key,regions,'wowmap/nav/'+key)
            masks[key,n]=walk_mask(p,scene,token_cells=n)
        mask,step=masks[key,n];x,y=row['position']
        forbidden=[r['shapes'][0]['bounds'] for r in p['foundry']['regions']]+occupied[key]
        candidates=[(x+dx*.5,y+dy*.5) for dx in range(-10,11) for dy in range(-10,11)]
        candidates.sort(key=lambda q:(math.dist(q,(x,y)),q))
        for cx,cy in candidates:
            box=[cx-n/2,cy-n/2,cx+n/2,cy+n/2]
            if not (0<=cx<p['size_cells'][0] and 0<=cy<p['size_cells'][1]):continue
            if not mask[int(cy/step),int(cx/step)] or any(overlap(box,b) for b in forbidden):continue
            if find_path(mask,step,starts[key],(cx,cy)) is None:continue
            row['position']=[cx,cy];occupied[key].append(box);break
        else:raise ValueError('No safe placement near '+row['id'])
    return rows


def main():
    author();SOURCE.mkdir(parents=True,exist_ok=True)
    documents=[]
    for key,row in STATS.items():
        (SOURCE/(key+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        entry=dict(id=key,mode='npc',source=str((SOURCE/(key+'.json')).relative_to(ROOT)))
        entry['item_icons']={i['system']['identifier']:ITEM_ICONS[i['system']['identifier']] for i in row['items']}
        if key in APPEARANCES:
            entry['appearance']=dict(APPEARANCES[key],size=512,portrait_size=640,yaw=TOKEN_ANGLES[key],portrait_yaw=PORTRAIT_ANGLES[key])
        documents.append(entry)
    request=dict(format='foundry-builder.batch/1',require_item_icons=True,require_explicit_angles=True,documents=documents,placements=placements())
    (ROOT/'requests/builder/void-crypt.json').write_text(json.dumps(request,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    text=['# Крипта Бездны DEV2-R4: бестиарий','',
          'Авторские тестовые NPC для пяти персонажей 6 уровня. Foundry 13.351 / dnd5e 5.3.3.','',
          'Оценка CR предварительная. Для отдельного первого теста босса восстановить ресурсы группы; для полного прохождения предусмотрены две возможности короткого отдыха. Необязательные бои обходятся. Не активировать все группы этажа одновременно.','']
    for key,row in STATS.items():
        s=row['system'];text.extend(['## '+row['name'],'',f"КД {s['attributes']['ac']['flat']}; хиты {s['attributes']['hp']['max']} ({s['attributes']['hp']['formula']}); CR {s['details']['cr']}; размер {s['traits']['size']}.",
            ' / '.join(f"{k.upper()} {v['value']}" for k,v in s['abilities'].items()),''])
        import re
        text.append(re.sub('<[^>]+>',' ',html.unescape(s['details']['biography']['value'])))
        for item in row['items']:text.extend(['','### '+item['name'],'',html.unescape(re.sub('<[^>]+>','',item['system']['description']['value']))])
        text.append('')
    (ROOT/'VOID_CRYPT_BESTIARY.md').write_text('\n'.join(text),encoding='utf-8')
    print(json.dumps(dict(actors=len(STATS),placements=len(request['placements']),items=sum(len(r['items']) for r in STATS.values()))))


if __name__=='__main__':main()
