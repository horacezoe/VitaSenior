"""Authored fictional prescription excerpts, NOT patient-specific prescribing.
Source citations and assumptions are recorded in docs/样例用药说明.md.
No run-time interaction rules or model-generated prescriptions live here.
"""
from copy import deepcopy

# name, dose, context. Existing slot IDs remain stable for history references.
CATALOG = {
 1: [('盐酸二甲双胍缓释片','500 mg，每日1次，随晚餐口服，整片吞服','18:30')],
 2: [('苯磺酸氨氯地平片','2.5 mg，每日1次，口服','08:00')],
 3: [('阿托伐他汀钙片','10 mg，每日1次，口服','20:00')],
 4: [('阿司匹林肠溶片','81 mg，每日1次，口服，整片吞服','08:00'),('阿托伐他汀钙片','20 mg，每日1次，口服','20:00')],
 5: [('阿司匹林肠溶片','81 mg，每日1次，口服，整片吞服','08:00')],
 6: [('噻托溴铵吸入粉雾剂','18 微克，每日1次，使用配套吸入器吸入；胶囊不得吞服','08:00'),('阿托伐他汀钙片','10 mg，每日1次，口服','20:00')],
 7: [],
 8: [('盐酸雷洛昔芬片','60 mg，每日1次，口服，可与食物同服',None)],
 9: [('别嘌醇片','100 mg，每日1次，餐后口服','08:00')],
 10:[('苯磺酸氨氯地平片','2.5 mg，每日1次，口服','08:00')],
 11:[('苯磺酸氨氯地平片','2.5 mg，每日1次，口服','08:00'),('盐酸二甲双胍片','850 mg，每日1次，随午餐口服',None)],
 12:[('苯磺酸氨氯地平片','2.5 mg，每日1次，口服','08:00'),('盐酸二甲双胍片','850 mg，每日1次，随午餐口服',None),('阿托伐他汀钙片','10 mg，每日1次，口服','20:00')],
 13:[],
}
CONTEXT = {
 1:'2型糖尿病稳定随访；设定eGFR 78 mL/min/1.73m²，无严重肝病、缺氧或急性脱水。所列为既有处方片段。',
 2:'原发性高血压稳定随访，既有低剂量方案，无已登记症状性低血压。',
 3:'血脂异常稳定随访，无活动性肝病；喜欢和家人做饭。',
 4:'稳定冠心病二级预防；无活动性出血、消化性溃疡或阿司匹林过敏；青霉素曾引起皮疹。',
 5:'非心源性缺血性脑卒中后遗症，左侧活动不便；无出血性卒中或活动性出血。这里只展示抗血小板处方片段，不代表完整二级预防方案。',
 6:'稳定期慢性阻塞性肺疾病，合并血脂异常；设定eGFR 75，无窄角青光眼或尿潴留。吸入胶囊只经配套装置吸入，不可口服，不作为急救药。',
 7:'膝骨关节炎随访；未设每日口服镇痛药，保留活动与症状核对。',
 8:'绝经后骨质疏松既有方案；无静脉血栓、卒中或冠心病史，无长期制动。饮食钙和维生素D摄入在随访中核对；这里只展示处方片段。',
 9:'反复痛风的降尿酸随访，非急性发作；设定eGFR 85，HLA-B*58:01筛查阴性、既往耐受，无硫唑嘌呤或巯嘌呤用药。',
 10:'慢性肾脏病G3a合并高血压；设定eGFR 52 mL/min/1.73m²，血钾4.5 mmol/L，无水肿或心衰。展示既有降压方案，并非仅凭肾病诊断开药。青霉素曾引起皮疹。',
 11:'高血压与2型糖尿病稳定随访；设定eGFR 76，无严重肝病、缺氧或脱水。',
 12:'高血压、2型糖尿病和血脂异常稳定随访；设定eGFR 72，无活动性肝病。',
 13:'无已登记基础慢病或长期用药，保留空计划。',
}

def upgrade_samples(legacy):
    result=deepcopy(legacy)
    for index, prescriptions in CATALOG.items():
        sample=result[f'community_sample_{index:03d}']
        sample['community_name']='银龄社区健康服务中心'
        profile=sample['profile']
        profile['conditions']=[s.replace('（演示档案）','') for s in profile['conditions']]
        profile['allergies']=['青霉素（皮疹）'] if index in {4,10} else []
        if index==5:profile['conditions']=['缺血性脑卒中后遗症']
        if index==6:profile['conditions']=['慢性阻塞性肺疾病','血脂异常']
        if index==10:profile['conditions']=['慢性肾脏病G3a','高血压']
        profile['medical_notes']=CONTEXT[index]
        assert len(prescriptions)==len(sample['medication_templates'])
        for template,(name,dose,clock) in zip(sample['medication_templates'],prescriptions):
            plan=template['plan'];plan['name'],plan['dose_display']=name,dose
            plan['notes']='既有处方信息，建档时由本人核对；不自动调整。'
            if clock:
                plan['schedule']={'mode':'fixed','slots':[{'slot_id':plan['schedule']['slots'][0]['slot_id'],'local_time':clock}]}
            else:
                plan['schedule']['slots'][0]['delay_minutes']=0
        sample['history_medication']=[dict(plan_key=t['template_key'],slot_id=s['slot_id']) for t in sample['medication_templates'] for s in t['plan']['schedule']['slots']]
    return result
